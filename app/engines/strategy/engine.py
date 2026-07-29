"""자산축적형·조기구매형을 같은 시나리오와 공식 가중치로 비교하는 순수 엔진.

이 파일은 미래 집값, 미래 대출한도 또는 현금흐름을 추정하지 않는다. 호출자가
근거와 함께 제공한 값만 계산하며, 결측은 0으로 바꾸지 않고 UNKNOWN 또는
임시점수로 보존한다.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.engines.strategy.models import (
    HousingCostScenario,
    StrategyCandidateInput,
    StrategyComparisonInput,
    StrategyComparisonResult,
    StrategyComparisonStatus,
    StrategyEvaluation,
    StrategyKind,
    StrategyPolicy,
    StrategyScenarioResult,
    StrategyScenarioStatus,
    StrategyScoreComponents,
    StrategyScoreStatus,
)


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _scenario_cost(scenario: HousingCostScenario, kind: StrategyKind) -> Decimal:
    if kind is StrategyKind.ASSET_ACCUMULATION:
        return scenario.asset_accumulation_total_cost
    return scenario.early_purchase_total_cost


def evaluate_strategy_scenario(
    candidate: StrategyCandidateInput,
    scenario: HousingCostScenario,
) -> StrategyScenarioResult:
    """한 전략의 자금조달 가능 여부를 주택가격 시나리오 하나에 대해 계산한다."""

    cost = _scenario_cost(scenario, candidate.kind)
    equity = candidate.available_equity
    loan = candidate.loan_capacity
    missing: list[str] = []

    if equity is None:
        missing.append("available_equity")
        return StrategyScenarioResult(
            scenario=scenario,
            strategy=candidate.kind,
            target_purchase_cost=cost,
            available_equity=None,
            loan_capacity=loan,
            required_equity=None,
            equity_only_gap=None,
            expected_loan_amount=None,
            funding_capacity=None,
            funding_shortfall=None,
            coverage_ratio=None,
            status=StrategyScenarioStatus.UNKNOWN,
            missing_inputs=tuple(missing),
            reasons=(
                "구매시점 자기자본이 확인되지 않아 시나리오 달성 여부를 판단하지 않았습니다.",
            ),
        )

    equity_gap = max(cost - equity, Decimal(0))
    if equity_gap == 0:
        return StrategyScenarioResult(
            scenario=scenario,
            strategy=candidate.kind,
            target_purchase_cost=cost,
            available_equity=equity,
            loan_capacity=loan,
            required_equity=cost,
            equity_only_gap=Decimal(0),
            expected_loan_amount=Decimal(0),
            funding_capacity=equity,
            funding_shortfall=Decimal(0),
            coverage_ratio=Decimal(1),
            status=StrategyScenarioStatus.PASS,
            reasons=("확인된 자기자본만으로 총구매비용을 충당할 수 있습니다.",),
        )

    if loan is None:
        missing.append("loan_capacity")
        return StrategyScenarioResult(
            scenario=scenario,
            strategy=candidate.kind,
            target_purchase_cost=cost,
            available_equity=equity,
            loan_capacity=None,
            required_equity=None,
            equity_only_gap=equity_gap,
            expected_loan_amount=None,
            funding_capacity=None,
            funding_shortfall=None,
            coverage_ratio=None,
            status=StrategyScenarioStatus.UNKNOWN,
            missing_inputs=tuple(missing),
            reasons=(
                f"자기자본만으로는 {equity_gap:,.0f}원이 부족하지만 "
                "대출계획이 확인되지 않아 최종 부족액을 판단하지 않았습니다.",
            ),
        )

    required_equity = max(cost - loan, Decimal(0))
    funding_capacity = equity + loan
    funding_shortfall = max(cost - funding_capacity, Decimal(0))
    expected_loan = min(equity_gap, loan)
    coverage = min(funding_capacity / cost, Decimal(1))
    status = (
        StrategyScenarioStatus.PASS
        if funding_shortfall == 0
        else StrategyScenarioStatus.FAIL
    )
    reasons = (
        ("확인된 자기자본과 계획 대출금으로 총구매비용을 충당할 수 있습니다.",)
        if status is StrategyScenarioStatus.PASS
        else (f"확인된 자금조달 계획으로 {funding_shortfall:,.0f}원이 부족합니다.",)
    )
    return StrategyScenarioResult(
        scenario=scenario,
        strategy=candidate.kind,
        target_purchase_cost=cost,
        available_equity=equity,
        loan_capacity=loan,
        required_equity=required_equity,
        equity_only_gap=equity_gap,
        expected_loan_amount=expected_loan,
        funding_capacity=funding_capacity,
        funding_shortfall=funding_shortfall,
        coverage_ratio=coverage,
        status=status,
        reasons=reasons,
    )


def _cost_scores(
    asset: StrategyCandidateInput,
    early: StrategyCandidateInput,
) -> dict[StrategyKind, Decimal]:
    """두 전략의 확인된 총금융비용만 상대 정규화한다.

    기존 대출추천 엔진과 같은 최소·최대 정규화를 사용한다. 하나라도 비용 범위가
    미확정이면 둘을 서로 비교할 수 없으므로 비용점수를 모두 결측으로 둔다.
    """

    if asset.total_financial_cost is None or early.total_financial_cost is None:
        return {}
    costs = {
        StrategyKind.ASSET_ACCUMULATION: asset.total_financial_cost,
        StrategyKind.EARLY_PURCHASE: early.total_financial_cost,
    }
    minimum = min(costs.values())
    maximum = max(costs.values())
    if minimum == maximum:
        return {kind: Decimal(1) for kind in costs}
    return {
        kind: Decimal(1) - (cost - minimum) / (maximum - minimum)
        for kind, cost in costs.items()
    }


@dataclass(frozen=True)
class _UnscoredEvaluation:
    candidate: StrategyCandidateInput
    scenarios: tuple[StrategyScenarioResult, ...]
    scenario_coverage: Decimal | None
    attainable_count: int
    unattainable_count: int
    unknown_count: int
    goal_timing: Decimal | None
    target_extension_required: bool | None
    target_delay_days: int | None


def _evaluate_unscored(
    candidate: StrategyCandidateInput,
    payload: StrategyComparisonInput,
) -> _UnscoredEvaluation:
    scenarios = tuple(
        evaluate_strategy_scenario(candidate, scenario)
        for scenario in payload.housing_scenarios
    )
    attainable = sum(result.status is StrategyScenarioStatus.PASS for result in scenarios)
    unattainable = sum(result.status is StrategyScenarioStatus.FAIL for result in scenarios)
    unknown = sum(result.status is StrategyScenarioStatus.UNKNOWN for result in scenarios)
    coverage = (
        None
        if unknown
        else Decimal(attainable) / Decimal(len(payload.housing_scenarios))
    )

    planned = candidate.planned_purchase_date
    if planned is None:
        goal_timing = None
        extension = None
        delay_days = None
    else:
        extension = planned > payload.target_purchase_date
        delay_days = max((planned - payload.target_purchase_date).days, 0)
        # 공식 설계안은 목표시점 적합성의 세부 감점식을 정하지 않았으므로
        # 임의의 선형감점을 만들지 않고 목표일 준수 여부를 1/0으로 판정한다.
        goal_timing = Decimal(0) if extension else Decimal(1)

    return _UnscoredEvaluation(
        candidate=candidate,
        scenarios=scenarios,
        scenario_coverage=coverage,
        attainable_count=attainable,
        unattainable_count=unattainable,
        unknown_count=unknown,
        goal_timing=goal_timing,
        target_extension_required=extension,
        target_delay_days=delay_days,
    )


def _apply_score(
    evaluation: _UnscoredEvaluation,
    *,
    cost_score: Decimal | None,
    policy: StrategyPolicy,
    target_purchase_date: date,
) -> StrategyEvaluation:
    candidate = evaluation.candidate
    components = StrategyScoreComponents(
        scenario_attainment=evaluation.scenario_coverage,
        cashflow_stability=candidate.cashflow_stability_score,
        total_financial_cost=cost_score,
        goal_timing=evaluation.goal_timing,
        plan_flexibility=candidate.plan_flexibility_score,
    )
    values = {
        "scenario_attainment": components.scenario_attainment,
        "cashflow_stability": components.cashflow_stability,
        "total_financial_cost": components.total_financial_cost,
        "goal_timing": components.goal_timing,
        "plan_flexibility": components.plan_flexibility,
    }
    known_weight = sum(
        (
            policy.weights[name]
            for name, value in values.items()
            if value is not None
        ),
        Decimal(0),
    )
    missing_components = tuple(name for name, value in values.items() if value is None)
    if known_weight < policy.minimum_score_completeness:
        score = None
        score_status = StrategyScoreStatus.UNAVAILABLE
    else:
        weighted_sum = sum(
            (
                policy.weights[name] * value
                for name, value in values.items()
                if value is not None
            ),
            Decimal(0),
        )
        score = Decimal(100) * weighted_sum / known_weight
        score_status = (
            StrategyScoreStatus.COMPLETE
            if known_weight == Decimal(1)
            else StrategyScoreStatus.PROVISIONAL
        )

    baseline = next(result for result in evaluation.scenarios if result.scenario.is_baseline)
    missing_inputs = list(candidate.missing_inputs)
    for result in evaluation.scenarios:
        missing_inputs.extend(result.missing_inputs)
    if candidate.planned_purchase_date is None:
        missing_inputs.append("planned_purchase_date")
    if candidate.cashflow_stability_score is None:
        missing_inputs.append("cashflow_stability_score")
    if candidate.total_financial_cost is None:
        missing_inputs.append("total_financial_cost")
    if candidate.plan_flexibility_score is None:
        missing_inputs.append("plan_flexibility_score")

    reasons = [
        f"주택가격 시나리오 {len(evaluation.scenarios)}개 중 PASS "
        f"{evaluation.attainable_count}, FAIL {evaluation.unattainable_count}, "
        f"UNKNOWN {evaluation.unknown_count}",
    ]
    if score_status is StrategyScoreStatus.PROVISIONAL:
        reasons.append(
            "일부 전략항목이 없어 확인된 항목만 재가중한 임시 점수입니다: "
            + ", ".join(missing_components)
        )
    elif score_status is StrategyScoreStatus.UNAVAILABLE:
        reasons.append(
            "확인된 전략항목의 가중치가 부족해 점수를 만들지 않았습니다: "
            + ", ".join(missing_components)
        )
    if evaluation.target_extension_required:
        reasons.append(
            f"예상 구매일이 목표일보다 {evaluation.target_delay_days}일 늦습니다."
        )

    return StrategyEvaluation(
        kind=candidate.kind,
        planned_purchase_date=candidate.planned_purchase_date,
        target_purchase_date=target_purchase_date,
        target_extension_required=evaluation.target_extension_required,
        target_delay_days=evaluation.target_delay_days,
        available_equity=candidate.available_equity,
        loan_capacity=candidate.loan_capacity,
        monthly_savings_amount=candidate.monthly_savings_amount,
        monthly_loan_payment=candidate.monthly_loan_payment,
        total_financial_cost=candidate.total_financial_cost,
        expected_net_savings_interest=candidate.expected_net_savings_interest,
        baseline_required_equity=baseline.required_equity,
        baseline_expected_loan_amount=baseline.expected_loan_amount,
        baseline_funding_shortfall=baseline.funding_shortfall,
        scenarios=evaluation.scenarios,
        attainable_count=evaluation.attainable_count,
        unattainable_count=evaluation.unattainable_count,
        unknown_count=evaluation.unknown_count,
        scenario_coverage=evaluation.scenario_coverage,
        score=score,
        score_status=score_status,
        score_completeness=known_weight,
        score_components=components,
        missing_score_components=missing_components,
        missing_inputs=_dedupe(missing_inputs),
        assumptions=_dedupe(candidate.assumptions),
        reasons=tuple(reasons),
    )


def compare_strategies(payload: StrategyComparisonInput) -> StrategyComparisonResult:
    """두 전략을 같은 공식과 시나리오 집합으로 비교한다."""

    asset_unscored = _evaluate_unscored(payload.asset_accumulation, payload)
    early_unscored = _evaluate_unscored(payload.early_purchase, payload)
    cost_scores = _cost_scores(payload.asset_accumulation, payload.early_purchase)
    asset = _apply_score(
        asset_unscored,
        cost_score=cost_scores.get(StrategyKind.ASSET_ACCUMULATION),
        policy=payload.policy,
        target_purchase_date=payload.target_purchase_date,
    )
    early = _apply_score(
        early_unscored,
        cost_score=cost_scores.get(StrategyKind.EARLY_PURCHASE),
        policy=payload.policy,
        target_purchase_date=payload.target_purchase_date,
    )

    both_infeasible = all(
        evaluation.unknown_count == 0 and evaluation.attainable_count == 0
        for evaluation in (asset, early)
    )
    comparable_scores = asset.score is not None and early.score is not None
    is_tie = False
    leading: StrategyKind | None = None
    if comparable_scores:
        asset_attainable = asset.attainable_count > 0
        early_attainable = early.attainable_count > 0
        if asset_attainable and not early_attainable:
            leading = StrategyKind.ASSET_ACCUMULATION
        elif early_attainable and not asset_attainable:
            leading = StrategyKind.EARLY_PURCHASE
        elif asset_attainable and early_attainable:
            difference = asset.score - early.score
            is_tie = abs(difference) <= payload.policy.score_tie_tolerance
            if not is_tie:
                leading = (
                    StrategyKind.ASSET_ACCUMULATION
                    if difference > 0
                    else StrategyKind.EARLY_PURCHASE
                )

    if both_infeasible:
        status = StrategyComparisonStatus.INFEASIBLE
    elif (
        comparable_scores
        and asset.score_status is StrategyScoreStatus.COMPLETE
        and early.score_status is StrategyScoreStatus.COMPLETE
    ):
        status = StrategyComparisonStatus.COMPLETE
    elif comparable_scores:
        status = StrategyComparisonStatus.PROVISIONAL
    else:
        status = StrategyComparisonStatus.UNAVAILABLE

    recommended = leading if status is StrategyComparisonStatus.COMPLETE else None
    reasons: list[str] = []
    if status is StrategyComparisonStatus.COMPLETE:
        if is_tie:
            reasons.append("공식 전략점수가 동점 허용범위 안이므로 단일 전략을 강요하지 않습니다.")
        elif leading is not None:
            reasons.append(
                f"달성 가능한 시나리오가 있고 완전한 비교를 통과한 "
                f"{leading.value}을(를) 추천합니다."
            )
    elif status is StrategyComparisonStatus.PROVISIONAL:
        reasons.append(
            "임시 점수상 선두 전략은 표시하지만 결측값 확인 전 최종 추천으로 확정하지 않습니다."
        )
    elif status is StrategyComparisonStatus.INFEASIBLE:
        reasons.append(
            "확인된 자금계획으로 두 전략 모두 모든 주택가격 시나리오를 달성하지 못합니다."
        )
    else:
        reasons.append("두 전략을 같은 기준으로 비교할 만큼 확인된 점수항목이 부족합니다.")

    missing = _dedupe(asset.missing_inputs + early.missing_inputs)
    return StrategyComparisonResult(
        status=status,
        as_of=payload.as_of,
        target_purchase_date=payload.target_purchase_date,
        asset_accumulation=asset,
        early_purchase=early,
        leading_strategy=leading,
        recommended_strategy=recommended,
        is_tie=is_tie,
        missing_inputs=missing,
        reasons=tuple(reasons),
        policy_note=payload.policy.policy_note,
        disclaimers=(
            "미래 주택가격과 미래 대출한도는 예측값이 아니라 호출자가 제공한 시나리오 가정입니다.",
            "전략 결과는 금융기관의 대출 승인이나 실제 상품 가입을 보장하지 않습니다.",
            "UNKNOWN 항목은 실패나 0점이 아니며 확인 전에는 최종 전략을 확정하지 않습니다.",
        ),
    )
