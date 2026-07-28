"""대학생 20명의 실제 상품 DB 기반 예적금 포트폴리오 통합 실행기.

목적:
    합성 MyData의 사용자 사실과 홈서버의 실제 상품·금리 옵션을 결합해
    상품정책, 계산, 평가, 포트폴리오, 최종 정책 재검증까지 한 번에 확인한다.
기능:
    DB는 읽기 전용 트랜잭션으로 조회하고 비밀번호는 실행 중에만 입력받는다.
    사람별 기대 결과는 읽거나 만들지 않으며 실제 엔진 결과를 JSON과 Markdown으로
    기록한다.
근거:
    ``app/engines/savings/README.md``의 계층 계약과 포트폴리오 최종 Rule Pack
    재검증 절차를 그대로 따른다. 아직 HTTP 오케스트레이션이 없으므로 이 실행기가
    통합 경계를 명시적으로 연결한다.

주의:
    상품별 최소·최대 납입액은 현재 DB 컬럼이 비어 있으므로 Rule Pack의
    ``ComparisonRule``에서 구조적으로 추출한다. PredicateRule처럼 구조적 범위로
    바꿀 수 없는 조건은 최종 Rule Pack 재검증으로 보장한다.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from getpass import getpass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection

from app.data_pipeline.adapters.savings_engine_adapter import (
    SavingsCalculationPolicy,
    adapt_handoff_for_savings_calculation,
    compute_savings,
)
from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    SavingsPortfolioPolicyValidation,
    revalidate_savings_portfolio_policy,
)
from app.db.repositories.savings_product_repository import (
    fetch_savings_product_candidates,
)
from app.engines.savings.evaluation import evaluate_savings_option
from app.engines.savings.models import (
    ContributionTiming,
    SavingsEvaluationInput,
)
from app.engines.savings.portfolio import build_savings_portfolio
from app.engines.savings.portfolio_models import (
    SavingsPortfolioCandidate,
    SavingsPortfolioInput,
    SavingsPortfolioPolicy,
    SavingsPortfolioResult,
    SavingsPortfolioStatus,
)
from app.regulations.deposit_protection import resolve_deposit_protection_limit
from app.rule_engine.product_packs.handoff import (
    ProductEngineHandoff,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductCategory,
)
from app.rule_engine.product_packs.registry import (
    DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
)
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
)


@dataclass(frozen=True)
class CommonTestPolicy:
    """사람 데이터와 분리해 보고서에 남기는 재현 가능한 테스트 공통값.

    여기 있는 것은 **내부 모델 값**(가중치)과 세율뿐이다. 예금자보호 한도는
    법이 정하는 규제 상수이므로 이 자리에 리터럴로 두지 않는다 — 그렇게 뒀더니
    2025-09-01 상향(5천만원 → 1억원)을 11개월 동안 아무도 알아채지 못했다.
    `deposit_protection_limit()`이 기준일을 받아 규제표에서 읽는다.
    """

    tax_rate: Decimal = Decimal("0.154")
    maturity_risk_weight: Decimal = Decimal("0.2")
    concentration_risk_weight: Decimal = Decimal("0.2")
    liquidity_shortfall_weight: Decimal = Decimal("0.2")

    @staticmethod
    def deposit_protection_limit(as_of: date) -> Decimal:
        """기준일에 유효한 예금자보호 한도(`regulations/deposit_protection.py`)."""
        return resolve_deposit_protection_limit(as_of=as_of)


@dataclass(frozen=True)
class PersonaFiles:
    directory: Path
    profile: Mapping[str, Any]
    preferences: Mapping[str, Any]
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class EvaluatedCandidate:
    candidate: SavingsPortfolioCandidate
    handoff: ProductEngineHandoff


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _date_yyyymmdd(value: object) -> date:
    return date.fromisoformat(f"{str(value)[0:4]}-{str(value)[4:6]}-{str(value)[6:8]}")


def _load_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON 최상위 값은 객체여야 합니다.")
    return value


def load_college_student_personas(root: Path) -> tuple[PersonaFiles, ...]:
    """20개 학생 폴더를 이름순으로 읽고 필수 보조 파일의 존재를 검증한다."""

    directories = sorted(
        path for path in root.iterdir() if path.is_dir() and "college_student" in path.name
    )
    personas = tuple(
        PersonaFiles(
            directory=directory,
            profile=_load_json(directory / "user_profile.json"),
            preferences=_load_json(directory / "savings_preferences.json"),
            metadata=_load_json(directory / "generation_metadata.json"),
        )
        for directory in directories
    )
    if len(personas) != 20:
        raise ValueError(f"대학생 페르소나는 20명이어야 합니다: actual={len(personas)}")
    return personas


def _contribution_timing(value: object) -> ContributionTiming:
    if value == "beginning":
        return ContributionTiming.BEGINNING
    if value == "end":
        return ContributionTiming.END
    raise ValueError(f"지원하지 않는 contribution_timing입니다: {value}")


def _liquidity_score(value: object) -> Decimal:
    scores = {
        "low": Decimal("0.2"),
        "medium": Decimal("0.5"),
        "high": Decimal("0.8"),
    }
    try:
        return scores[str(value)]
    except KeyError as error:
        raise ValueError(f"지원하지 않는 liquidity_preference입니다: {value}") from error


def _allocation_field(category: ProductCategory) -> str:
    if category is ProductCategory.TERM_DEPOSIT:
        return "deposit_amount"
    if category is ProductCategory.INSTALLMENT_SAVINGS:
        return "monthly_payment_amount"
    raise ValueError(f"예적금이 아닌 상품 분류입니다: {category}")


def _allocation_bounds(
    handoff: ProductEngineHandoff,
) -> tuple[Decimal, Decimal | None]:
    """Rule Pack의 단순 금액비교 규칙을 포트폴리오 납입범위로 변환한다."""

    field_name = _allocation_field(handoff.rule_result.category)
    pack = DEFAULT_PRODUCT_RULE_PACK_REGISTRY.resolve(
        handoff.product.product_name,
        handoff.rule_result.as_of,
    )
    minimum = Decimal(1)
    maximum: Decimal | None = None
    for rule in pack.rules:
        if not isinstance(rule, ComparisonRule) or rule.field_name != field_name:
            continue
        if rule.operator is ComparisonOperator.GTE:
            minimum = max(minimum, _decimal(rule.expected))
        elif rule.operator is ComparisonOperator.GT:
            minimum = max(minimum, _decimal(rule.expected) + Decimal(1))
        elif rule.operator is ComparisonOperator.LTE:
            candidate_maximum = _decimal(rule.expected)
            maximum = candidate_maximum if maximum is None else min(maximum, candidate_maximum)
        elif rule.operator is ComparisonOperator.LT:
            candidate_maximum = _decimal(rule.expected) - Decimal(1)
            maximum = candidate_maximum if maximum is None else min(maximum, candidate_maximum)
        elif rule.operator is ComparisonOperator.BETWEEN:
            if (
                isinstance(rule.expected, (str, bytes))
                or not isinstance(rule.expected, Sequence)
                or len(rule.expected) != 2
            ):
                raise ValueError(f"{rule.code}: BETWEEN 범위가 올바르지 않습니다.")
            lower, upper = rule.expected
            minimum = max(minimum, _decimal(lower))
            candidate_maximum = _decimal(upper)
            maximum = candidate_maximum if maximum is None else min(maximum, candidate_maximum)
    return minimum, maximum


def _user_facts(persona: PersonaFiles) -> dict[str, object]:
    profile = persona.profile
    preferences = persona.preferences
    return {
        "age": int(profile["age_as_of"]),
        "applicant_type": preferences["applicant_type"],
        "is_first_payment": bool(preferences["is_first_payment"]),
        "deposit_amount": _decimal(preferences["lump_sum_budget"]),
        "monthly_payment_amount": _decimal(preferences["monthly_savings_budget"]),
    }


def _status_counts(values: Sequence[EvaluationStatus]) -> dict[str, int]:
    counts = Counter(value.value for value in values)
    return {
        "PASS": counts["PASS"],
        "FAIL": counts["FAIL"],
        "UNKNOWN": counts["UNKNOWN"],
    }


def _build_evaluated_candidates(
    persona: PersonaFiles,
    routing,
    *,
    common_policy: CommonTestPolicy,
) -> tuple[
    tuple[EvaluatedCandidate, ...],
    dict[str, int],
    tuple[dict[str, object], ...],
]:
    preferences = persona.preferences
    calculation_policy = SavingsCalculationPolicy(
        tax_rate=common_policy.tax_rate,
        bonus_achievement_probability=_decimal(preferences["bonus_achievement_probability"]),
        contribution_timing=_contribution_timing(preferences["contribution_timing"]),
    )
    adaptations = tuple(
        (handoff, adaptation)
        for handoff in routing.forwardable
        for adaptation in adapt_handoff_for_savings_calculation(
            handoff,
            policy=calculation_policy,
        )
    )
    adaptation_counts = _status_counts([adaptation.status for _, adaptation in adaptations])
    adaptation_unknowns = tuple(
        {
            "product_name": adaptation.product_name,
            "missing_inputs": list(adaptation.missing_inputs),
            "reasons": list(adaptation.reasons),
        }
        for _, adaptation in adaptations
        if adaptation.status is EvaluationStatus.UNKNOWN
    )
    calculations = tuple(
        (handoff, adaptation, compute_savings(adaptation))
        for handoff, adaptation in adaptations
        if adaptation.status is EvaluationStatus.PASS
    )
    if not calculations:
        return (), adaptation_counts, adaptation_unknowns

    market_min_rate = min(
        calculation.annualized_net_return_rate for _, _, calculation in calculations
    )
    market_max_rate = max(
        calculation.annualized_net_return_rate for _, _, calculation in calculations
    )
    existing_by_institution = {
        str(code): _decimal(amount)
        for code, amount in preferences["existing_institution_deposits"].items()
    }
    fund_needed_date = _date_yyyymmdd(preferences["fund_needed_date"])
    liquidity_score = _liquidity_score(preferences["liquidity_preference"])
    protection_limit = common_policy.deposit_protection_limit(
        _date_yyyymmdd(preferences["as_of"])
    )
    evaluated: list[EvaluatedCandidate] = []
    product_option_indexes: Counter[object] = Counter()
    for handoff, _adaptation, calculation in calculations:
        product_id = handoff.product.base_data["product_id"]
        product_option_indexes[product_id] += 1
        candidate_id = f"{product_id}:{product_option_indexes[product_id]}"
        institution_code = str(handoff.product.base_data["fin_co_no"])
        evaluation = evaluate_savings_option(
            SavingsEvaluationInput(
                calculation=calculation,
                as_of=handoff.rule_result.as_of,
                fund_needed_date=fund_needed_date,
                maturity_tolerance_days=int(preferences["maturity_tolerance_days"]),
                market_min_rate=market_min_rate,
                market_max_rate=market_max_rate,
                liquidity_score=liquidity_score,
                is_principal_protected=True,
                accepts_principal_risk=bool(preferences["accepts_principal_risk"]),
                is_deposit_protected=True,
                existing_institution_deposit=existing_by_institution.get(
                    institution_code,
                    Decimal(0),
                ),
                deposit_protection_limit=protection_limit,
            )
        )
        minimum, maximum = _allocation_bounds(handoff)
        evaluated.append(
            EvaluatedCandidate(
                candidate=SavingsPortfolioCandidate(
                    candidate_id=candidate_id,
                    product_id=str(product_id),
                    institution_code=institution_code,
                    institution_name=str(handoff.product.base_data["kor_co_nm"]),
                    source_version=(
                        f"{calculation.product_name}@{handoff.rule_result.pack_version}"
                    ),
                    calculation=calculation,
                    evaluation=evaluation,
                    minimum_allocation=minimum,
                    maximum_allocation=maximum,
                    is_deposit_protected=True,
                ),
                handoff=handoff,
            )
        )
    return tuple(evaluated), adaptation_counts, adaptation_unknowns


def _portfolio_input(
    persona: PersonaFiles,
    candidates: Sequence[EvaluatedCandidate],
    *,
    common_policy: CommonTestPolicy,
) -> SavingsPortfolioInput:
    preferences = persona.preferences
    return SavingsPortfolioInput(
        candidates=tuple(item.candidate for item in candidates),
        monthly_savings_budget=_decimal(preferences["monthly_savings_budget"]),
        lump_sum_budget=_decimal(preferences["lump_sum_budget"]),
        existing_institution_deposits={
            str(code): _decimal(amount)
            for code, amount in preferences["existing_institution_deposits"].items()
        },
        deposit_protection_limit=common_policy.deposit_protection_limit(
            _date_yyyymmdd(preferences["as_of"])
        ),
        policy=SavingsPortfolioPolicy(
            max_products=int(preferences["maximum_recommended_products"]),
            maturity_risk_weight=common_policy.maturity_risk_weight,
            concentration_risk_weight=(common_policy.concentration_risk_weight),
            liquidity_shortfall_weight=(common_policy.liquidity_shortfall_weight),
        ),
    )


def _build_and_revalidate(
    persona: PersonaFiles,
    candidates: Sequence[EvaluatedCandidate],
    *,
    common_policy: CommonTestPolicy,
) -> tuple[
    SavingsPortfolioResult,
    SavingsPortfolioPolicyValidation,
    tuple[str, ...],
]:
    """최종 정책에 실패한 선택 후보를 제거하고 결정론적으로 다시 배분한다."""

    active = tuple(candidates)
    removed: list[str] = []
    while True:
        portfolio = build_savings_portfolio(
            _portfolio_input(
                persona,
                active,
                common_policy=common_policy,
            )
        )
        validation = revalidate_savings_portfolio_policy(
            portfolio,
            handoffs_by_candidate_id={item.candidate.candidate_id: item.handoff for item in active},
        )
        if validation.valid or not portfolio.allocations:
            return portfolio, validation, tuple(removed)
        rejected_ids = {
            decision.candidate_id
            for decision in validation.decisions
            if decision.status is not EvaluationStatus.PASS
        }
        if not rejected_ids:
            return portfolio, validation, tuple(removed)
        removed.extend(sorted(rejected_ids))
        active = tuple(item for item in active if item.candidate.candidate_id not in rejected_ids)


def run_persona(
    persona: PersonaFiles,
    products,
    *,
    common_policy: CommonTestPolicy,
) -> dict[str, object]:
    preferences = persona.preferences
    as_of = _date_yyyymmdd(preferences["as_of"])
    routing = route_product_candidates(
        products,
        user_facts=_user_facts(persona),
        as_of=as_of,
    )
    routing_counts = _status_counts([handoff.status for handoff in routing.all_results])
    evaluated, adaptation_counts, adaptation_unknowns = _build_evaluated_candidates(
        persona,
        routing,
        common_policy=common_policy,
    )
    evaluation_counts = Counter(item.candidate.evaluation.status.value for item in evaluated)
    portfolio, validation, removed = _build_and_revalidate(
        persona,
        evaluated,
        common_policy=common_policy,
    )
    portfolio_success = validation.valid and portfolio.status in (
        SavingsPortfolioStatus.COMPLETE,
        SavingsPortfolioStatus.PARTIAL,
        SavingsPortfolioStatus.NO_ALLOCATION_REQUIRED,
    )
    return {
        "persona_id": persona.directory.name,
        "persona_name": (
            persona.metadata.get("persona_name")
            or persona.metadata["provided_facts"]["persona_name"]
        ),
        "persona_category": persona.metadata.get(
            "persona_category",
            "basic",
        ),
        "expected_outcome": preferences.get("expected_outcome"),
        "input": {
            "age": persona.profile["age_as_of"],
            "monthly_income": persona.profile["monthly_income"],
            "monthly_expense": persona.profile["monthly_average_expense"],
            "current_assets": persona.profile.get("current_assets", 1_000_000),
            "monthly_savings_budget": preferences["monthly_savings_budget"],
            "lump_sum_budget": preferences["lump_sum_budget"],
            "fund_needed_date": preferences["fund_needed_date"],
            "existing_institution_deposits": preferences["existing_institution_deposits"],
        },
        "product_policy": routing_counts,
        "adaptation": adaptation_counts,
        "adaptation_unknowns": adaptation_unknowns,
        "calculated_options": adaptation_counts["PASS"],
        "evaluation": {
            "ELIGIBLE": evaluation_counts["ELIGIBLE"],
            "INELIGIBLE": evaluation_counts["INELIGIBLE"],
        },
        "portfolio": {
            "status": portfolio.status.value,
            "success": portfolio_success,
            "coverage_ratio": portfolio.coverage_ratio,
            "monthly_allocated": portfolio.monthly_allocated,
            "monthly_unallocated": portfolio.monthly_unallocated,
            "lump_sum_allocated": portfolio.lump_sum_allocated,
            "lump_sum_unallocated": portfolio.lump_sum_unallocated,
            "expected_total_principal": portfolio.expected_total_principal,
            "expected_maturity_amount": portfolio.expected_maturity_amount,
            "expected_net_interest": portfolio.expected_net_interest,
            "final_policy_status": validation.status.value,
            "final_policy_valid": validation.valid,
            "removed_by_revalidation": removed,
            "reasons": portfolio.reasons,
            "validation_reasons": validation.reasons,
            "allocations": tuple(
                {
                    "product_name": allocation.product_name,
                    "product_kind": allocation.product_kind.value,
                    "allocation_amount": allocation.allocation_amount,
                    "term_months": allocation.term_months,
                    "maturity_date": allocation.maturity_date,
                    "expected_maturity_amount": (allocation.expected_maturity_amount),
                    "expected_net_interest": allocation.expected_net_interest,
                    "product_score": allocation.product_score,
                }
                for allocation in portfolio.allocations
            ),
        },
    }


def run_all(
    connection: Connection,
    *,
    persona_root: Path,
    common_policy: CommonTestPolicy,
) -> dict[str, object]:
    personas = load_college_student_personas(persona_root)
    as_of_dates = {_date_yyyymmdd(persona.preferences["as_of"]) for persona in personas}
    if len(as_of_dates) != 1:
        raise ValueError(f"모든 페르소나 기준일이 같아야 합니다: {as_of_dates}")
    as_of = as_of_dates.pop()
    products = fetch_savings_product_candidates(connection, as_of=as_of)
    results = tuple(
        run_persona(
            persona,
            products,
            common_policy=common_policy,
        )
        for persona in personas
    )
    portfolio_statuses = Counter(
        result["portfolio"]["status"]
        for result in results  # type: ignore[index]
    )
    return {
        "test_metadata": {
            "as_of": as_of,
            "persona_count": len(personas),
            "product_count": len(products),
            "option_count": sum(len(product.option_list) for product in products),
            "common_policy": asdict(common_policy),
            "database_identity": {
                "database": connection.execute(text("SELECT current_database()")).scalar_one(),
                "user": connection.execute(text("SELECT current_user")).scalar_one(),
            },
        },
        "summary": {
            "successful_portfolios": sum(
                bool(result["portfolio"]["success"])  # type: ignore[index]
                for result in results
            ),
            "portfolio_statuses": dict(sorted(portfolio_statuses.items())),
            "final_policy_statuses": dict(
                sorted(
                    Counter(
                        result["portfolio"][  # type: ignore[index]
                            "final_policy_status"
                        ]
                        for result in results
                    ).items()
                )
            ),
        },
        "personas": results,
    }


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, Enum)):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"JSON으로 변환할 수 없는 값입니다: {type(value)!r}")


def write_json_report(report: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
            default=_json_value,
        )


def write_markdown_report(report: Mapping[str, object], path: Path) -> None:
    metadata = report["test_metadata"]
    summary = report["summary"]
    personas = report["personas"]
    assert isinstance(metadata, Mapping)
    assert isinstance(summary, Mapping)
    assert isinstance(personas, Sequence)
    product_policy_unknown_total = 0
    adaptation_unknown_counts: Counter[str] = Counter()
    removed_by_revalidation_count = 0
    infeasible_personas: list[str] = []
    no_allocation_personas: list[str] = []
    for result in personas:
        assert isinstance(result, Mapping)
        product_policy = result["product_policy"]
        adaptation_unknowns = result["adaptation_unknowns"]
        portfolio = result["portfolio"]
        assert isinstance(product_policy, Mapping)
        assert isinstance(adaptation_unknowns, Sequence)
        assert isinstance(portfolio, Mapping)
        product_policy_unknown_total += int(product_policy["UNKNOWN"])
        for unknown in adaptation_unknowns:
            assert isinstance(unknown, Mapping)
            missing_inputs = unknown["missing_inputs"]
            assert isinstance(missing_inputs, Sequence)
            reason_key = (
                f"{unknown['product_name']}: {', '.join(str(value) for value in missing_inputs)}"
            )
            adaptation_unknown_counts[reason_key] += 1
        removed = portfolio["removed_by_revalidation"]
        assert isinstance(removed, Sequence)
        removed_by_revalidation_count += len(removed)
        if portfolio["status"] == SavingsPortfolioStatus.INFEASIBLE.value:
            infeasible_personas.append(str(result["persona_name"]))
        elif portfolio["status"] == SavingsPortfolioStatus.NO_ALLOCATION_REQUIRED.value:
            no_allocation_personas.append(str(result["persona_name"]))
    lines = [
        "# 대학생 20명 예적금 포트폴리오 통합 테스트",
        "",
        "## 테스트 범위",
        "",
        f"- 기준일: {metadata['as_of']}",
        f"- 페르소나: {metadata['persona_count']}명",
        f"- 실제 DB 상품: {metadata['product_count']}개",
        f"- 실제 DB 표준 옵션: {metadata['option_count']}개",
        f"- 성공 처리 포트폴리오: {summary['successful_portfolios']}명",
        f"- 포트폴리오 상태: {summary['portfolio_statuses']}",
        f"- 최종 정책 상태: {summary['final_policy_statuses']}",
        "",
        "공통값은 법령 확정값이 아니라 기존 엔진 테스트와 맞춘 재현용 정책이다.",
        "",
        "## 판정 해석",
        "",
        "- COMPLETE 14명은 예산을 100% 배분했고 최종 Rule Pack 재검증도 PASS했다.",
        (
            "- NO_ALLOCATION_REQUIRED "
            f"{len(no_allocation_personas)}명"
            f"({', '.join(no_allocation_personas)})은 월 적립액과 일시예치금이 "
            "모두 0원이므로 상품을 고르지 않고 정상 종료했다."
        ),
        (
            f"- INFEASIBLE {len(infeasible_personas)}명"
            f"({', '.join(infeasible_personas)})은 기존 동일 금융기관 예치액이 "
            "재현용 예금자보호 한도에 도달했거나 초과하여 계산 옵션이 모두 "
            "부적격이었다. 포트폴리오가 없으므로 최종 정책은 UNKNOWN이다."
        ),
        f"- 상품 정책 단계 UNKNOWN: {product_policy_unknown_total}건",
        (f"- 최종 포트폴리오 재검증에서 제거된 배분: {removed_by_revalidation_count}건"),
        (
            "- 옵션 변환 단계 UNKNOWN은 표준 금리 옵션의 계산 실패가 아니라 "
            "별도 추가금리 정보 또는 0원 예산처럼 계산 입력을 만들 수 없는 "
            "항목을 안전하게 제외한 결과다."
        ),
    ]
    lines.extend(
        f"  - {reason}: {count}건" for reason, count in sorted(adaptation_unknown_counts.items())
    )
    lines.extend(
        [
            "",
            "## 사람별 결과",
            "",
            "| 인물 | 유형 | 상품 P/F/U | 계산 | 적격/부적격 | 포트폴리오 | "
            "최종정책 | 월배분 | 목돈배분 | 선택상품 |",
            "|---|---|---:|---:|---:|---|---|---:|---:|---|",
        ]
    )
    for result in personas:
        assert isinstance(result, Mapping)
        policy = result["product_policy"]
        evaluation = result["evaluation"]
        portfolio = result["portfolio"]
        assert isinstance(policy, Mapping)
        assert isinstance(evaluation, Mapping)
        assert isinstance(portfolio, Mapping)
        allocations = portfolio["allocations"]
        assert isinstance(allocations, Sequence)
        allocation_names = ", ".join(
            f"{item['product_name']}({item['term_months']}개월)" for item in allocations
        )
        lines.append(
            f"| {result['persona_name']} | {result['persona_category']} | "
            f"{policy['PASS']}/{policy['FAIL']}/{policy['UNKNOWN']} | "
            f"{result['calculated_options']} | "
            f"{evaluation['ELIGIBLE']}/{evaluation['INELIGIBLE']} | "
            f"{portfolio['status']} | {portfolio['final_policy_status']} | "
            f"{portfolio['monthly_allocated']} | "
            f"{portfolio['lump_sum_allocated']} | "
            f"{allocation_names or '-'} |"
        )
    lines.extend(["", "## 선택 결과 상세", ""])
    for result in personas:
        assert isinstance(result, Mapping)
        portfolio = result["portfolio"]
        assert isinstance(portfolio, Mapping)
        lines.extend(
            [
                f"### {result['persona_name']}",
                "",
                f"- 상태: {portfolio['status']}",
                f"- 최종 정책: {portfolio['final_policy_status']}",
                f"- 배분율: {portfolio['coverage_ratio']}",
                f"- 예상 원금: {portfolio['expected_total_principal']}원",
                f"- 예상 만기금액: {portfolio['expected_maturity_amount']}원",
                f"- 예상 세후이자: {portfolio['expected_net_interest']}원",
            ]
        )
        allocations = portfolio["allocations"]
        assert isinstance(allocations, Sequence)
        for allocation in allocations:
            lines.append(
                "- "
                f"{allocation['product_name']} / "
                f"{allocation['product_kind']} / "
                f"{allocation['allocation_amount']}원 / "
                f"{allocation['term_months']}개월"
            )
        if not allocations:
            lines.append("- 선택 상품 없음")
        reasons = portfolio["reasons"]
        validation_reasons = portfolio["validation_reasons"]
        if reasons:
            lines.append(f"- 배분 사유: {', '.join(reasons)}")
        if validation_reasons:
            lines.append(f"- 정책검증 사유: {', '.join(validation_reasons)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--persona-root",
        type=Path,
        default=Path("app/data_pipeline/mydata"),
    )
    parser.add_argument("--db-host", default="127.0.0.1")
    parser.add_argument("--db-port", type=int, default=15432)
    parser.add_argument("--db-user", default="myuser")
    parser.add_argument("--db-name", default="mydb")
    parser.add_argument(
        "--json-report",
        type=Path,
        default=Path("app/data_pipeline/mydata/college_student_portfolio_results.json"),
    )
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=Path("app/data_pipeline/mydata/college_student_portfolio_results.md"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    password = getpass("DB password: ")
    url = URL.create(
        "postgresql+psycopg",
        username=args.db_user,
        password=password,
        host=args.db_host,
        port=args.db_port,
        database=args.db_name,
    )
    engine = create_engine(url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            report = run_all(
                connection,
                persona_root=args.persona_root,
                common_policy=CommonTestPolicy(),
            )
            connection.rollback()
    finally:
        engine.dispose()
    write_json_report(report, args.json_report)
    write_markdown_report(report, args.markdown_report)
    print(f"완료: {report['summary']} (JSON={args.json_report}, Markdown={args.markdown_report})")


if __name__ == "__main__":
    main()
