"""Pure property-level affordability decision using existing engine results."""

from decimal import Decimal

from app.engines.affordability.models import (
    AffordabilityVerdict,
    PropertyAffordabilityInput,
    PropertyAffordabilityResult,
)
from app.engines.affordability.policy import (
    DEFAULT_AFFORDABILITY_POLICY,
    AffordabilityPolicy,
)
from app.engines.loan.combination_models import CombinationStatus
from app.engines.purchase_costs.models import PurchaseCostEngineStatus


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _loan_funding_amount(
    payload: PropertyAffordabilityInput,
    evaluated_required_loan: Decimal,
) -> Decimal | None:
    if evaluated_required_loan == 0:
        return Decimal(0)
    combination = payload.loan_combination
    if combination is None or combination.status is CombinationStatus.UNRESOLVED:
        return None
    if combination.best is not None:
        return combination.best.total_amount
    if combination.status is CombinationStatus.INFEASIBLE:
        return Decimal(0)
    return None


def _validate_combination_target(
    payload: PropertyAffordabilityInput,
    evaluated_required_loan: Decimal,
) -> None:
    combination = payload.loan_combination
    if combination is None or combination.best is None:
        return
    plan_target = combination.best.total_amount + combination.best.funding_shortfall
    if plan_target != evaluated_required_loan:
        raise ValueError("loan combination was calculated for a different required amount")


def evaluate_property_affordability(
    payload: PropertyAffordabilityInput,
    *,
    policy: AffordabilityPolicy = DEFAULT_AFFORDABILITY_POLICY,
) -> PropertyAffordabilityResult:
    """Decide one listing without turning an unknown amount into zero."""

    costs = payload.purchase_costs
    total_cost = costs.total_purchase_cost
    evaluated_cost = total_cost or costs.minimum_total_purchase_cost
    own_funds_used = min(payload.usable_liquid_assets, evaluated_cost)
    remaining_liquid = payload.usable_liquid_assets - own_funds_used
    minimum_required_loan = max(
        costs.minimum_total_purchase_cost - payload.usable_liquid_assets,
        Decimal(0),
    )
    required_loan = (
        None if total_cost is None else max(total_cost - payload.usable_liquid_assets, Decimal(0))
    )
    evaluated_required_loan = max(
        evaluated_cost - payload.usable_liquid_assets,
        Decimal(0),
    )

    _validate_combination_target(payload, evaluated_required_loan)
    loan_funding = _loan_funding_amount(
        payload,
        evaluated_required_loan,
    )
    minimum_gap = (
        None if loan_funding is None else max(minimum_required_loan - loan_funding, Decimal(0))
    )
    gap = (
        None
        if required_loan is None or loan_funding is None
        else max(required_loan - loan_funding, Decimal(0))
    )
    selected = (
        None
        if evaluated_required_loan == 0 or payload.loan_combination is None
        else payload.loan_combination.best
    )

    reasons: list[str] = [
        (
            f"최소 필요자금은 매물가 {payload.purchase_price:,.0f}원과 "
            f"현재 확인된 부대비용 {costs.known_ancillary_costs:,.0f}원을 합한 "
            f"{costs.minimum_total_purchase_cost:,.0f}원입니다."
        ),
        (
            f"비상자금 목표 {payload.emergency_fund_target:,.0f}원을 우선 분리하고 "
            f"사용 가능한 유동자산 {payload.usable_liquid_assets:,.0f}원만 "
            "주택 구매 자기자금으로 평가했습니다."
        ),
    ]
    missing: list[str] = list(costs.missing_inputs)
    assumptions: list[str] = [
        *payload.cashflow_assumptions,
        *payload.loan_assumptions,
        *costs.assumptions,
        policy.policy_note,
    ]

    combination = payload.loan_combination
    if evaluated_required_loan > 0 and combination is not None:
        missing.extend(combination.missing_inputs)
        reasons.extend(combination.reasons)
        if combination.policy_note:
            assumptions.append(combination.policy_note)

    if selected is not None:
        names = ", ".join(selected.product_names) or "선택된 대출 조합"
        reasons.append(
            f"선택 대출 조합은 {names}이며 총 {selected.total_amount:,.0f}원을 조달합니다."
        )
        assumptions.extend(selected.assumptions)
    elif evaluated_required_loan > 0:
        if combination is None and not payload.loan_missing_inputs:
            missing.append("loan_combination")
        missing.extend(payload.loan_missing_inputs)
        reasons.extend(payload.loan_reasons)

    if costs.status is PurchaseCostEngineStatus.UNSUPPORTED:
        verdict = AffordabilityVerdict.UNSUPPORTED
        reasons.extend(costs.reasons)
    elif costs.status is PurchaseCostEngineStatus.POLICY_OUT_OF_RANGE:
        verdict = AffordabilityVerdict.UNKNOWN
        reasons.extend(costs.reasons)
    elif total_cost is None:
        if minimum_gap is not None and minimum_gap > policy.funding_tolerance:
            verdict = AffordabilityVerdict.SHORTFALL
            reasons.append(f"확인된 최소 비용만 기준으로도 {minimum_gap:,.0f}원이 부족합니다.")
        else:
            verdict = AffordabilityVerdict.UNKNOWN
            reasons.append(
                "미확정 부대비용이 있어 현재 최소금액을 조달할 수 있더라도 "
                "최종 구매 가능 여부는 확정하지 않았습니다."
            )
    elif loan_funding is None:
        verdict = AffordabilityVerdict.UNKNOWN
        if evaluated_required_loan > 0:
            reasons.append(
                "필요 대출금액은 계산됐지만 실행 가능한 대출 조합을 확정하지 못했습니다."
            )
    elif gap is not None and gap > policy.funding_tolerance:
        verdict = AffordabilityVerdict.SHORTFALL
        reasons.append(f"현재 자기자금과 대출 조합으로 {gap:,.0f}원이 부족합니다.")
    else:
        tight_reasons: list[str] = []
        if gap is not None and gap > 0:
            tight_reasons.append(f"자금 차이 {gap:,.0f}원이 계산 허용오차 안에만 들어옵니다.")
        if payload.protected_liquid_assets < payload.emergency_fund_target:
            shortage = payload.emergency_fund_target - payload.protected_liquid_assets
            tight_reasons.append(f"구매 전에도 비상자금 목표 대비 {shortage:,.0f}원이 부족합니다.")
        if (
            selected is not None
            and selected.stress_monthly_surplus < payload.cashflow_buffer_target
        ):
            tight_reasons.append("스트레스 심사금리 기준 월 잉여가 현금흐름 Buffer보다 작습니다.")
        if tight_reasons:
            verdict = AffordabilityVerdict.TIGHT
            reasons.extend(tight_reasons)
        else:
            verdict = AffordabilityVerdict.AFFORDABLE
            reasons.append(
                "현재 확인된 비용, 보호한 비상자금, 자기자금 및 대출 제약을 "
                "모두 반영해 구매 가능 범위로 판정했습니다."
            )

    return PropertyAffordabilityResult(
        as_of=payload.as_of,
        policy_version=policy.version,
        listing_id=payload.listing_id,
        verdict=verdict,
        purchase_price=payload.purchase_price,
        purchase_costs=costs,
        minimum_total_purchase_cost=costs.minimum_total_purchase_cost,
        total_purchase_cost=total_cost,
        evaluated_purchase_cost=evaluated_cost,
        usable_liquid_assets_before_purchase=payload.usable_liquid_assets,
        own_funds_used=own_funds_used,
        remaining_usable_liquid_assets=remaining_liquid,
        emergency_fund_target=payload.emergency_fund_target,
        protected_liquid_assets=payload.protected_liquid_assets,
        minimum_required_loan_amount=minimum_required_loan,
        required_loan_amount=required_loan,
        loan_combination_status=(
            None if payload.loan_combination is None else payload.loan_combination.status
        ),
        selected_loan_plan=selected,
        loan_funding_amount=loan_funding,
        minimum_funding_gap=minimum_gap,
        funding_gap=gap,
        monthly_loan_payment=(None if selected is None else selected.monthly_payment),
        post_purchase_monthly_surplus=(
            None if selected is None else selected.post_purchase_monthly_surplus
        ),
        stress_monthly_surplus=(None if selected is None else selected.stress_monthly_surplus),
        missing_inputs=_dedupe(missing),
        reasons=_dedupe(reasons),
        assumptions=_dedupe(assumptions),
        policy_sources=_dedupe(
            [
                *payload.cashflow_policy_sources,
                *costs.policy_sources,
                *payload.loan_policy_sources,
            ]
        ),
    )
