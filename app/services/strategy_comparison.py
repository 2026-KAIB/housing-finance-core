"""종합추천·스트레스 결과를 두 주택구매 전략의 순수 입력으로 조립한다.

목적:
    대출·예적금·전략 계층의 책임을 섞지 않고 이미 검증된 결과만 전달한다.
기능:
    조기구매형에는 현재 추천대출과 생활 스트레스 결과를, 자산축적형에는
    정책검증을 통과한 예적금 만기금액과 호출자 제공 미래계획을 연결한다.
근거:
    공식 설계안 §15~16은 현재 구매와 저축 후 구매를 같은 시나리오로 비교하되
    확정적인 미래 집값·대출 승인을 제시하지 않도록 요구한다.
"""

from datetime import date
from decimal import Decimal

from app.engines.recommendation.models import (
    CombinedRecommendationResult,
    ComponentStatus,
)
from app.engines.savings.models import SavingsProductKind
from app.engines.strategy.engine import compare_strategies
from app.engines.strategy.models import (
    DEFAULT_STRATEGY_POLICY,
    HousingCostScenario,
    StrategyCandidateInput,
    StrategyComparisonInput,
    StrategyComparisonResult,
    StrategyKind,
    StrategyPolicy,
)
from app.engines.stress.models import StressTestResult


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _verified_accumulation_values(
    recommendation: CombinedRecommendationResult,
    *,
    additional_accumulation_equity: Decimal,
    explicit_purchase_date: date | None,
) -> tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    date | None,
    tuple[str, ...],
    tuple[str, ...],
]:
    """예적금 만기액과 겹치지 않는 추가자금을 합쳐 미래 자기자본을 만든다.

    ``additional_accumulation_equity``는 포트폴리오의
    ``expected_maturity_amount``에 이미 들어간 원금·이자를 제외한 금액이다.
    이 경계를 명시해 현재 목돈 원금을 만기액에 다시 더하는 중복계산을 막는다.
    """

    savings = recommendation.savings
    missing: list[str] = list(savings.missing_inputs)
    assumptions = [
        "추가 축적자금은 예적금 포트폴리오 예상 만기액과 중복되지 않는 금액입니다.",
    ]
    verified_statuses = (ComponentStatus.READY, ComponentStatus.PARTIAL)
    if savings.status in verified_statuses:
        available_equity = additional_accumulation_equity + savings.expected_maturity_amount
        monthly_savings = sum(
            (
                allocation.allocation_amount
                for allocation in savings.allocations
                if allocation.product_kind
                == SavingsProductKind.INSTALLMENT_SAVINGS.value
            ),
            Decimal(0),
        )
        net_interest = savings.expected_net_interest
        purchase_date = explicit_purchase_date or (
            max(allocation.maturity_date for allocation in savings.allocations)
            if savings.allocations
            else None
        )
        assumptions.append("상품정책을 통과한 배분안의 예상 만기액만 미래 자기자본에 반영했습니다.")
        if savings.status is ComponentStatus.PARTIAL:
            assumptions.append(
                "부분 배분안이므로 포트폴리오 밖의 자금은 추가 축적자금에 포함해야 합니다."
            )
    elif savings.status is ComponentStatus.NOT_REQUIRED:
        available_equity = additional_accumulation_equity
        monthly_savings = Decimal(0)
        net_interest = Decimal(0)
        purchase_date = explicit_purchase_date
        assumptions.append("배분할 예적금 예산이 없어 추가 축적자금만 반영했습니다.")
    else:
        available_equity = None
        monthly_savings = None
        net_interest = None
        purchase_date = explicit_purchase_date
        missing.append("verified_savings_maturity_amount")
        assumptions.append("검증된 예적금 만기액이 없어 구매시점 자기자본을 확정하지 않았습니다.")

    return (
        available_equity,
        monthly_savings,
        net_interest,
        purchase_date,
        _dedupe(missing),
        _dedupe(assumptions),
    )


def compare_recommended_purchase_strategies(
    recommendation: CombinedRecommendationResult,
    *,
    target_purchase_date: date,
    housing_scenarios: tuple[HousingCostScenario, ...],
    early_purchase_equity: Decimal,
    additional_accumulation_equity: Decimal,
    stress_result: StressTestResult | None = None,
    early_purchase_date: date | None = None,
    asset_accumulation_purchase_date: date | None = None,
    future_loan_capacity: Decimal | None = None,
    future_monthly_loan_payment: Decimal | None = None,
    future_total_financial_cost: Decimal | None = None,
    asset_cashflow_stability_score: Decimal | None = None,
    early_cashflow_stability_score: Decimal | None = None,
    asset_plan_flexibility_score: Decimal | None = None,
    early_plan_flexibility_score: Decimal | None = None,
    policy: StrategyPolicy = DEFAULT_STRATEGY_POLICY,
) -> StrategyComparisonResult:
    """현재 종합추천을 자산축적형·조기구매형 비교로 확장한다.

    미래 대출 관련 인수는 향후 시점의 정책·금리·소득을 자동 예측한 값이 아니다.
    호출자가 별도 근거로 마련한 계획값만 넣어야 하며, 없으면 ``None``을 유지한다.
    """

    if early_purchase_equity < 0:
        raise ValueError("early_purchase_equity은(는) 음수일 수 없습니다.")
    if additional_accumulation_equity < 0:
        raise ValueError("additional_accumulation_equity은(는) 음수일 수 없습니다.")
    if stress_result is not None and stress_result.as_of != recommendation.as_of:
        raise ValueError(
            "종합추천 기준일과 스트레스 결과 기준일이 다릅니다: "
            f"recommendation={recommendation.as_of}, stress={stress_result.as_of}"
        )

    (
        asset_equity,
        monthly_savings,
        net_savings_interest,
        accumulation_date,
        asset_missing,
        asset_assumptions,
    ) = _verified_accumulation_values(
        recommendation,
        additional_accumulation_equity=additional_accumulation_equity,
        explicit_purchase_date=asset_accumulation_purchase_date,
    )
    asset_missing_list = list(asset_missing)
    asset_assumption_list = list(asset_assumptions)
    if future_loan_capacity is None:
        asset_missing_list.append("future_loan_capacity")
    else:
        asset_assumption_list.append(
            "미래 대출한도는 호출자 제공 계획값이며 미래 승인이나 "
            "현재 정책의 지속을 보장하지 않습니다."
        )
    if asset_cashflow_stability_score is None:
        asset_missing_list.append("asset_cashflow_stability_score")
    if asset_plan_flexibility_score is None:
        asset_missing_list.append("asset_plan_flexibility_score")
    if future_total_financial_cost is None:
        asset_missing_list.append("future_total_financial_cost")

    primary = recommendation.loan.primary
    early_missing: list[str] = list(recommendation.loan.missing_inputs)
    early_assumptions: list[str] = []
    if primary is not None:
        early_loan_capacity = primary.recommended_amount
        early_monthly_payment = primary.monthly_payment
        early_total_cost = primary.total_financial_cost
        early_assumptions.append(
            f"현재 종합추천의 대출 {primary.product_name} / {primary.option_name}을 사용했습니다."
        )
    elif recommendation.loan.required_amount == 0:
        early_loan_capacity = Decimal(0)
        early_monthly_payment = Decimal(0)
        early_total_cost = Decimal(0)
        early_assumptions.append("현재 구매에 신규 대출이 필요하지 않은 계획입니다.")
    else:
        early_loan_capacity = None
        early_monthly_payment = None
        early_total_cost = None
        early_missing.append("recommended_loan_option")

    if early_cashflow_stability_score is not None:
        resolved_early_cashflow = early_cashflow_stability_score
        early_assumptions.append("호출자가 제공한 조기구매 현금흐름 안정성 점수를 사용했습니다.")
    elif stress_result is not None and stress_result.unknown_count == 0:
        resolved_early_cashflow = stress_result.pass_ratio
        early_assumptions.append(
            "조기구매 현금흐름 안정성은 생활 스트레스 시나리오 PASS 비율을 사용했습니다."
        )
    else:
        resolved_early_cashflow = None
        early_missing.append("early_cashflow_stability_score")
        if stress_result is not None and stress_result.unknown_count:
            early_assumptions.append(
                "스트레스 결과에 UNKNOWN이 있어 PASS 비율을 안정성 점수로 확정하지 않았습니다."
            )
    if early_total_cost is None:
        early_missing.append("early_total_financial_cost")
    if early_plan_flexibility_score is None:
        early_missing.append("early_plan_flexibility_score")

    asset = StrategyCandidateInput(
        kind=StrategyKind.ASSET_ACCUMULATION,
        planned_purchase_date=accumulation_date,
        available_equity=asset_equity,
        loan_capacity=future_loan_capacity,
        monthly_savings_amount=monthly_savings,
        monthly_loan_payment=future_monthly_loan_payment,
        total_financial_cost=future_total_financial_cost,
        expected_net_savings_interest=net_savings_interest,
        cashflow_stability_score=asset_cashflow_stability_score,
        plan_flexibility_score=asset_plan_flexibility_score,
        missing_inputs=_dedupe(asset_missing_list),
        assumptions=_dedupe(asset_assumption_list),
    )
    early = StrategyCandidateInput(
        kind=StrategyKind.EARLY_PURCHASE,
        planned_purchase_date=early_purchase_date or recommendation.as_of,
        available_equity=early_purchase_equity,
        loan_capacity=early_loan_capacity,
        monthly_loan_payment=early_monthly_payment,
        total_financial_cost=early_total_cost,
        cashflow_stability_score=resolved_early_cashflow,
        plan_flexibility_score=early_plan_flexibility_score,
        missing_inputs=_dedupe(early_missing),
        assumptions=_dedupe(early_assumptions),
    )
    return compare_strategies(
        StrategyComparisonInput(
            as_of=recommendation.as_of,
            target_purchase_date=target_purchase_date,
            housing_scenarios=housing_scenarios,
            asset_accumulation=asset,
            early_purchase=early,
            policy=policy,
        )
    )
