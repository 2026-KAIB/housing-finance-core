"""``SimulationInput``에서 예·적금 포트폴리오까지를 잇는 계층.

목적:
    상품정책 판정 → 계산 어댑터 → 옵션 평가 → 포트폴리오 배분 → 최종 Rule Pack
    재검증을 정해진 순서로 호출한다. 지금까지 이 순서를 아는 곳은 대학생
    페르소나 독립 실행기(`data_pipeline/mydata/run_college_student_portfolios.py`)
    뿐이었고, HTTP 경계에서는 아무도 부르지 않아 예·적금 구간이 늘 ``NOT_RUN``이었다.

대출 계층과 무엇이 다른가:
    **보수적인 방향이 반대다.** 대출은 모르는 값을 채우면 한도가 커져서 위험하고,
    예·적금은 모르는 값을 채우면 기대 수익이 커져서 위험하다. 그래서 파생 기본값을
    전부 수익이 낮아지는 쪽으로 둔다(우대 미달성, 말일 납입, 만기 지연 불허).

목돈을 대출 자기자본과 이중으로 세지 않는가:
    같은 돈이지만 **시점이 다르다.** 구매 시점까지 예치해 두었다가 그때 찾아
    자기자본으로 쓰는 것이므로, 두 계산이 같은 돈을 각자 한 번씩 쓴다. 다만
    만기가 필요 시점을 넘으면 정작 필요할 때 묶이므로, 평가 단계에 필요 시점을
    넘겨 만기위험으로 반영한다. 이 사실은 가정으로 남겨 보고서가 밝힌다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.data_pipeline.adapters.savings_engine_adapter import (
    SavingsCalculationPolicy,
    adapt_handoff_for_savings_calculation,
    compute_savings,
    resolve_allocation_bounds,
)
from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    SavingsPortfolioPolicyValidation,
    revalidate_savings_portfolio_policy,
)
from app.engines.cashflow.models import CashflowResult
from app.engines.savings.evaluation import evaluate_savings_option
from app.engines.savings.models import ContributionTiming, SavingsEvaluationInput
from app.engines.savings.portfolio import build_savings_portfolio
from app.engines.savings.portfolio_models import (
    SavingsPortfolioCandidate,
    SavingsPortfolioInput,
    SavingsPortfolioPolicy,
    SavingsPortfolioResult,
)
from app.regulations.deposit_protection import get_deposit_protection_limit
from app.rule_engine.product_packs.handoff import (
    ProductCandidate,
    ProductEngineHandoff,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import EvaluationStatus
from app.rule_engine.product_packs.registry import (
    DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
    ProductRulePackRegistry,
)
from app.schemas.simulation import SavingsRequestInput, SimulationInput

# 이자소득세 14%(소득세법 제129조 제1항 제1호) + 지방소득세 1.4%(지방세법 제92조,
# 소득세액의 10%) = 15.4%. 세금우대저축·비과세종합저축은 이보다 낮지만 그 자격은
# 자유텍스트 조건이라 판정하지 않는다(부록 B-3). 일반과세를 쓰면 만기 수령액을
# **낮게** 잡으므로 안전한 쪽이며, 그 사실을 가정으로 남긴다.
GENERAL_INTEREST_TAX_RATE = Decimal("0.154")

# 유동성 선호를 확인하지 못했을 때 쓰는 정책 중립값. 현금흐름 엔진이 미확인
# 위험 지표에 0.50을 쓰는 것과 같은 값·같은 이유다. 순위에만 쓰이고 제약이
# 아니므로 중립값이 성립한다.
_NEUTRAL_LIQUIDITY_SCORE = Decimal("0.5")

_LIQUIDITY_SCORES: dict[str, Decimal] = {
    "low": Decimal("0.2"),
    "medium": Decimal("0.5"),
    "high": Decimal("0.8"),
}

# 만기위험·기관집중도·유동성 패널티 가중치. 공식 설계안은 **위험 요소만** 정의하고
# 수치는 정하지 않았으므로 엔진이 숨은 상수를 두지 않고 호출자가 명시하게 되어 있다
# (`engines/savings/README.md`). 여기가 그 호출자이며, 이 값은 규제 상수가 아니라
# 서비스가 버전 관리하는 내부 값이다. 대학생 페르소나 실행기와 **같은 값**을 쓴다 —
# 두 경로가 다른 가중치를 쓰면 같은 사용자에게 다른 순위가 나온다.
SAVINGS_MATURITY_RISK_WEIGHT = Decimal("0.2")
SAVINGS_CONCENTRATION_RISK_WEIGHT = Decimal("0.2")
SAVINGS_LIQUIDITY_SHORTFALL_WEIGHT = Decimal("0.2")

_SAVINGS_BLOCK_MISSING = "savings_request"
_CANDIDATES_MISSING = "savings_product_candidates"
_BUDGET_MISSING = "monthly_savings_budget"
_PROTECTION_LIMIT_MISSING = "deposit_protection_limit"


@dataclass(frozen=True)
class SavingsPortfolioOutcome:
    """포트폴리오 결과와 그것을 만들 때 남긴 근거."""

    result: SavingsPortfolioResult
    validation: SavingsPortfolioPolicyValidation
    # 최종 Rule Pack 재검증에서 빠진 후보. 왜 안 보이는지에 답하는 자리다.
    removed_candidate_ids: tuple[str, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SavingsPortfolioBlocked:
    """계산을 시작하지 못한 상태. 0건이 아니라 **모름**이다."""

    missing_inputs: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class _Budget:
    monthly: Decimal
    lump_sum: Decimal
    fund_needed_date: date
    missing_inputs: tuple[str, ...]
    assumptions: tuple[str, ...]


def _contribution_timing(value: str) -> ContributionTiming:
    return (
        ContributionTiming.BEGINNING if value == "beginning" else ContributionTiming.END
    )


def _resolve_budget(
    payload: SimulationInput,
    request: SavingsRequestInput,
    *,
    cashflow_result: CashflowResult,
) -> _Budget | SavingsPortfolioBlocked:
    """예산 두 값을 정한다. 명시값이 우선이고, 없으면 현금흐름 진단에서 파생한다."""

    missing: list[str] = []
    assumptions: list[str] = []

    monthly = request.monthly_savings_budget
    if monthly is None:
        derived = cashflow_result.allocation.monthly_housing_savings_available
        if derived is None:
            return SavingsPortfolioBlocked(
                missing_inputs=(_BUDGET_MISSING,),
                reasons=(
                    "월 적금 예산이 없고 현금흐름 진단도 월 주택저축 가능액을 "
                    "확정하지 못해 예·적금 구간을 실행하지 않았습니다.",
                ),
            )
        monthly = derived
        assumptions.append(
            "월 적금 예산을 현금흐름 진단의 월 주택저축 가능액으로 파생했습니다. "
            "비상자금 적립분을 먼저 뺀 금액입니다."
        )

    lump_sum = request.lump_sum_budget
    if lump_sum is None:
        lump_sum = cashflow_result.emergency_fund.usable_liquid_assets_after_target
        assumptions.append(
            "일시예치 예산을 비상자금 목표를 뺀 사용 가능 유동자산으로 파생했습니다. "
            "이 금액은 대출 계산이 자기자본으로 보는 것과 같은 돈이며, "
            "구매 시점까지 예치했다가 그때 찾아 쓰는 것을 전제로 합니다."
        )

    fund_needed_date = request.fund_needed_date
    if fund_needed_date is None:
        fund_needed_date = payload.housing_goal.target_date
        assumptions.append("자금이 필요한 시점을 주택 목표 시점과 같다고 보았습니다.")

    if not request.existing_institution_deposits:
        # 비어 있는 것을 "없다"로 읽으면 예금자보호 한도를 회사별로 과대평가한다.
        missing.append("existing_institution_deposits")
        assumptions.append(
            "금융회사별 기존 예치액을 확인하지 못해 0원으로 두었습니다. "
            "실제 예치액이 있으면 예금자보호 한도 안의 배분 가능액이 줄어듭니다."
        )
    if request.liquidity_preference is None:
        missing.append("liquidity_preference")
        assumptions.append(
            "유동성 선호를 확인하지 못해 정책 중립값을 적용했습니다. "
            "순위에만 쓰이며 배분 제약은 아닙니다."
        )
    if request.bonus_achievement_probability == 0:
        assumptions.append(
            "우대금리를 달성하지 않는 것으로 보고 만기 수령액을 계산했습니다. "
            "우대조건 달성 여부는 상품 설명서에서 직접 확인해야 합니다."
        )
    assumptions.append(
        f"이자소득에 일반과세 {GENERAL_INTEREST_TAX_RATE * 100:.1f}%를 적용했습니다. "
        "세금우대·비과세 자격은 판정하지 않았습니다."
    )

    return _Budget(
        monthly=monthly,
        lump_sum=lump_sum,
        fund_needed_date=fund_needed_date,
        missing_inputs=tuple(missing),
        assumptions=tuple(assumptions),
    )


def _user_facts(
    payload: SimulationInput,
    request: SavingsRequestInput,
    *,
    budget: _Budget,
) -> dict[str, object]:
    """Rule Pack에 넘길 가입자 사실. **아는 것만 채운다**(부록 B-3)."""

    facts: dict[str, object] = {
        "age": payload.profile.age,
        "deposit_amount": budget.lump_sum,
        "monthly_payment_amount": budget.monthly,
    }
    if request.applicant_type is not None:
        facts["applicant_type"] = request.applicant_type
    if request.is_first_payment is not None:
        facts["is_first_payment"] = request.is_first_payment
    return facts


def _portfolio_input(
    candidates: Sequence[SavingsPortfolioCandidate],
    *,
    request: SavingsRequestInput,
    budget: _Budget,
    protection_limit: Decimal,
) -> SavingsPortfolioInput:
    return SavingsPortfolioInput(
        candidates=tuple(candidates),
        monthly_savings_budget=budget.monthly,
        lump_sum_budget=budget.lump_sum,
        existing_institution_deposits=dict(request.existing_institution_deposits),
        deposit_protection_limit=protection_limit,
        policy=SavingsPortfolioPolicy(
            max_products=request.maximum_recommended_products,
            maturity_risk_weight=SAVINGS_MATURITY_RISK_WEIGHT,
            concentration_risk_weight=SAVINGS_CONCENTRATION_RISK_WEIGHT,
            liquidity_shortfall_weight=SAVINGS_LIQUIDITY_SHORTFALL_WEIGHT,
        ),
    )


def _evaluated_candidates(
    handoffs: Sequence[ProductEngineHandoff],
    *,
    request: SavingsRequestInput,
    budget: _Budget,
    protection_limit: Decimal,
    registry: ProductRulePackRegistry,
) -> tuple[
    tuple[SavingsPortfolioCandidate, ...],
    dict[str, ProductEngineHandoff],
    tuple[str, ...],
]:
    """가입 가능한 상품의 옵션마다 계산·평가를 끝낸 포트폴리오 후보를 만든다."""

    policy = SavingsCalculationPolicy(
        tax_rate=GENERAL_INTEREST_TAX_RATE,
        bonus_achievement_probability=request.bonus_achievement_probability,
        contribution_timing=_contribution_timing(request.contribution_timing),
    )
    calculations = [
        (handoff, compute_savings(adaptation))
        for handoff in handoffs
        for adaptation in adapt_handoff_for_savings_calculation(handoff, policy=policy)
        if adaptation.status is EvaluationStatus.PASS
    ]
    if not calculations:
        return (), {}, ("계산 입력이 확정된 예·적금 옵션이 없습니다.",)

    # 금리 점수 정규화 범위는 후보군을 아는 이 계층이 정한다. 단일 상품
    # 계산기가 다른 후보를 조회하지 않게 하기 위한 계약이다.
    rates = [item.annualized_net_return_rate for _handoff, item in calculations]
    market_min, market_max = min(rates), max(rates)
    liquidity_score = (
        _NEUTRAL_LIQUIDITY_SCORE
        if request.liquidity_preference is None
        else _LIQUIDITY_SCORES[request.liquidity_preference]
    )

    candidates: list[SavingsPortfolioCandidate] = []
    handoff_by_id: dict[str, ProductEngineHandoff] = {}
    option_index: dict[object, int] = {}
    for handoff, calculation in calculations:
        product_id = handoff.product.base_data["product_id"]
        option_index[product_id] = option_index.get(product_id, 0) + 1
        candidate_id = f"{product_id}:{option_index[product_id]}"
        institution_code = str(handoff.product.base_data["fin_co_no"])
        evaluation = evaluate_savings_option(
            SavingsEvaluationInput(
                calculation=calculation,
                as_of=handoff.rule_result.as_of,
                fund_needed_date=budget.fund_needed_date,
                maturity_tolerance_days=request.maturity_tolerance_days,
                market_min_rate=market_min,
                market_max_rate=market_max,
                liquidity_score=liquidity_score,
                is_principal_protected=True,
                accepts_principal_risk=request.accepts_principal_risk,
                is_deposit_protected=True,
                existing_institution_deposit=request.existing_institution_deposits.get(
                    institution_code,
                    Decimal(0),
                ),
                deposit_protection_limit=protection_limit,
            )
        )
        minimum, maximum = resolve_allocation_bounds(handoff, registry=registry)
        candidates.append(
            SavingsPortfolioCandidate(
                candidate_id=candidate_id,
                product_id=str(product_id),
                institution_code=institution_code,
                institution_name=str(handoff.product.base_data["kor_co_nm"]),
                source_version=f"{calculation.product_name}@{handoff.rule_result.pack_version}",
                calculation=calculation,
                evaluation=evaluation,
                minimum_allocation=minimum,
                maximum_allocation=maximum,
                is_deposit_protected=True,
            )
        )
        handoff_by_id[candidate_id] = handoff
    return tuple(candidates), handoff_by_id, ()


def _build_and_revalidate(
    candidates: Sequence[SavingsPortfolioCandidate],
    handoff_by_id: Mapping[str, ProductEngineHandoff],
    *,
    request: SavingsRequestInput,
    budget: _Budget,
    protection_limit: Decimal,
) -> tuple[SavingsPortfolioResult, SavingsPortfolioPolicyValidation, tuple[str, ...]]:
    """최종 정책에 실패한 선택 후보를 빼고 결정론적으로 다시 배분한다.

    한 번만 배분하고 재검증에서 떨어뜨리면 사용자에게 **아무 안도 남지 않는다.**
    떨어진 후보만 빼고 남은 것으로 다시 배분해 실행 가능한 안을 남긴다.
    """
    active = tuple(candidates)
    removed: list[str] = []
    while True:
        portfolio = build_savings_portfolio(
            _portfolio_input(
                active,
                request=request,
                budget=budget,
                protection_limit=protection_limit,
            )
        )
        validation = revalidate_savings_portfolio_policy(
            portfolio,
            handoffs_by_candidate_id={
                candidate.candidate_id: handoff_by_id[candidate.candidate_id]
                for candidate in active
            },
        )
        if validation.valid or not portfolio.allocations:
            return portfolio, validation, tuple(removed)
        rejected = {
            decision.candidate_id
            for decision in validation.decisions
            if decision.status is not EvaluationStatus.PASS
        }
        if not rejected:
            return portfolio, validation, tuple(removed)
        removed.extend(sorted(rejected))
        active = tuple(
            candidate for candidate in active if candidate.candidate_id not in rejected
        )


def simulate_savings_portfolio(
    payload: SimulationInput,
    candidates: Sequence[ProductCandidate] = (),
    *,
    as_of: date,
    cashflow_result: CashflowResult,
    registry: ProductRulePackRegistry = DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
) -> SavingsPortfolioOutcome | SavingsPortfolioBlocked:
    """예·적금 구간을 끝까지 실행한다. 실행할 수 없으면 이유와 함께 막힌 상태를 낸다."""

    request = payload.savings_request
    if request is None:
        return SavingsPortfolioBlocked(
            missing_inputs=(_SAVINGS_BLOCK_MISSING,),
            reasons=(
                "예·적금 계산에 필요한 자금 필요시점·납입 취향·기존 예치액이 없어 "
                "예·적금 구간을 실행하지 않았습니다.",
            ),
        )
    if not candidates:
        # 후보 0건과 "가입 가능한 상품이 없음"은 다른 상태다.
        return SavingsPortfolioBlocked(
            missing_inputs=(_CANDIDATES_MISSING,),
            reasons=(
                "예·적금 상품 후보가 전달되지 않아 계산하지 않았습니다. "
                "후보 0건은 '조건을 만족하는 상품이 없음'과 다른 상태입니다.",
            ),
        )

    limit = get_deposit_protection_limit(as_of=as_of)
    if limit is None:
        # 한도를 모르는 채로 배분하면 보호 범위를 넘겨 배분할 수 있다.
        return SavingsPortfolioBlocked(
            missing_inputs=(_PROTECTION_LIMIT_MISSING,),
            reasons=(
                f"{as_of.isoformat()} 시점에 적용할 예금자보호 한도를 확정하지 못해 "
                "예·적금 구간을 실행하지 않았습니다.",
            ),
        )

    budget = _resolve_budget(payload, request, cashflow_result=cashflow_result)
    if isinstance(budget, SavingsPortfolioBlocked):
        return budget

    routing = route_product_candidates(
        candidates,
        user_facts=_user_facts(payload, request, budget=budget),
        as_of=as_of,
        registry=registry,
    )
    evaluated, handoff_by_id, calculation_reasons = _evaluated_candidates(
        routing.forwardable,
        request=request,
        budget=budget,
        protection_limit=limit.amount,
        registry=registry,
    )
    if not evaluated:
        return SavingsPortfolioBlocked(
            missing_inputs=budget.missing_inputs,
            reasons=(
                *calculation_reasons,
                f"상품정책 통과 {len(routing.forwardable)}건 / "
                f"자격 탈락 {len(routing.rejected)}건 / "
                f"입력 부족 {len(routing.needs_review)}건입니다.",
            ),
        )

    portfolio, validation, removed = _build_and_revalidate(
        evaluated,
        handoff_by_id,
        request=request,
        budget=budget,
        protection_limit=limit.amount,
    )
    reasons = [
        f"예금자보호 한도 {limit.amount:,.0f}원을 적용했습니다 (출처: {limit.source}).",
        f"상품정책 통과 {len(routing.forwardable)}건 / "
        f"자격 탈락 {len(routing.rejected)}건 / "
        f"입력 부족 {len(routing.needs_review)}건 중 계산까지 끝난 옵션 {len(evaluated)}건.",
    ]
    if removed:
        reasons.append(
            "최종 상품정책 재검증에서 제외한 후보: " + ", ".join(removed) + ". "
            "제외 후 남은 후보로 다시 배분했습니다."
        )
    return SavingsPortfolioOutcome(
        result=portfolio,
        validation=validation,
        removed_candidate_ids=removed,
        missing_inputs=budget.missing_inputs,
        reasons=tuple(reasons),
        assumptions=budget.assumptions,
    )


__all__ = [
    "GENERAL_INTEREST_TAX_RATE",
    "SavingsPortfolioBlocked",
    "SavingsPortfolioOutcome",
    "simulate_savings_portfolio",
]
