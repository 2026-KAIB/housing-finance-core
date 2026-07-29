"""추천 계획에 금리·소득·생활비 충격을 적용하는 결정론적 순수 엔진."""

from decimal import Decimal

from app.engines.loan.formulas import buffer, dsr, pmt
from app.engines.stress.models import (
    InterestRateShockApplicability,
    StressCheck,
    StressScenario,
    StressScenarioResult,
    StressScenarioStatus,
    StressTestInput,
    StressTestResult,
)


def _dedupe(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _stressed_values(
    payload: StressTestInput,
    scenario: StressScenario,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    income_factor = Decimal(1) - scenario.income_reduction_ratio
    expense_factor = Decimal(1) + scenario.living_expense_increase_ratio
    return (
        payload.annual_income * income_factor,
        payload.post_purchase_monthly_income * income_factor,
        payload.post_purchase_monthly_expense * expense_factor,
        payload.monthly_essential_expense * expense_factor,
    )


def _unknown_result(
    payload: StressTestInput,
    scenario: StressScenario,
    *,
    missing_inputs: tuple[str, ...],
    reasons: tuple[str, ...],
) -> StressScenarioResult:
    (
        stressed_annual_income,
        stressed_monthly_income,
        stressed_monthly_expense,
        stressed_essential_expense,
    ) = _stressed_values(payload, scenario)
    return StressScenarioResult(
        scenario=scenario,
        status=StressScenarioStatus.UNKNOWN,
        applied_annual_rate=None,
        stressed_annual_income=stressed_annual_income,
        stressed_monthly_income=stressed_monthly_income,
        stressed_monthly_expense=stressed_monthly_expense,
        stressed_monthly_essential_expense=stressed_essential_expense,
        monthly_payment=None,
        monthly_payment_increase=None,
        expected_dsr=None,
        safe_dsr=payload.safe_dsr,
        cashflow_before_savings=None,
        buffer_target=buffer(stressed_essential_expense),
        buffer_margin=None,
        monthly_savings_commitment=payload.monthly_savings_commitment,
        sustainable_monthly_savings=None,
        savings_shortfall=None,
        cashflow_after_savings=None,
        dsr_within_limit=None,
        buffer_maintained=None,
        savings_plan_maintainable=None,
        missing_inputs=_dedupe(missing_inputs),
        reasons=_dedupe(reasons),
    )


def _applied_rate(
    payload: StressTestInput,
    scenario: StressScenario,
) -> tuple[Decimal | None, tuple[str, ...], tuple[str, ...]]:
    """생활 시나리오 금리를 정한다. 규제 심사용 stress DSR 금리는 사용하지 않는다."""

    if payload.loan_principal == 0 or scenario.interest_rate_increase == 0:
        return payload.annual_rate, (), ()
    applicability = payload.interest_rate_shock_applicability
    if applicability is InterestRateShockApplicability.APPLIES:
        return (
            payload.annual_rate + scenario.interest_rate_increase,
            (),
            (
                f"추천대출 실제 금리에 {scenario.interest_rate_increase * 100:.2f}%p "
                "생활 시나리오 충격을 적용했습니다.",
            ),
        )
    if applicability is InterestRateShockApplicability.NOT_APPLIES:
        return (
            payload.annual_rate,
            (),
            ("고정금리로 확인되어 해당 기간의 금리 충격을 월 상환액에 적용하지 않았습니다.",),
        )
    return (
        None,
        ("interest_rate_shock_applicability",),
        ("금리유형 또는 고정기간을 확인할 수 없어 금리 충격 상환액을 계산하지 않았습니다.",),
    )


def evaluate_stress_scenario(
    payload: StressTestInput,
    scenario: StressScenario,
) -> StressScenarioResult:
    """시나리오 하나의 DSR·Buffer·적금 유지 가능성을 계산한다."""

    if payload.precondition_missing_inputs:
        return _unknown_result(
            payload,
            scenario,
            missing_inputs=payload.precondition_missing_inputs,
            reasons=("추천 계획의 필수 입력이 부족해 스트레스 계산을 시작하지 않았습니다.",),
        )

    applied_rate, rate_missing, rate_reasons = _applied_rate(payload, scenario)
    if applied_rate is None:
        return _unknown_result(
            payload,
            scenario,
            missing_inputs=rate_missing,
            reasons=rate_reasons,
        )

    (
        stressed_annual_income,
        stressed_monthly_income,
        stressed_monthly_expense,
        stressed_essential_expense,
    ) = _stressed_values(payload, scenario)
    base_payment = pmt(payload.loan_principal, payload.annual_rate, payload.months)
    monthly_payment = pmt(payload.loan_principal, applied_rate, payload.months)
    expected_dsr = dsr(
        existing_annual_debt_service=payload.existing_annual_debt_service,
        new_annual_debt_service=monthly_payment * Decimal(12),
        annual_income=stressed_annual_income,
    )
    cashflow_before_savings = (
        stressed_monthly_income
        - stressed_monthly_expense
        - payload.other_existing_monthly_debt_service
        - monthly_payment
    )
    buffer_target = buffer(stressed_essential_expense)
    buffer_margin = cashflow_before_savings - buffer_target
    dsr_within_limit = expected_dsr <= payload.safe_dsr
    buffer_maintained = cashflow_before_savings >= buffer_target

    missing_inputs: list[str] = list(rate_missing)
    commitment = payload.monthly_savings_commitment
    if commitment is None:
        sustainable_savings = None
        savings_shortfall = None
        cashflow_after_savings = None
        savings_maintainable = None
        missing_inputs.append("monthly_savings_commitment")
    else:
        available_for_savings = max(cashflow_before_savings - buffer_target, Decimal(0))
        sustainable_savings = min(commitment, available_for_savings)
        savings_shortfall = commitment - sustainable_savings
        cashflow_after_savings = cashflow_before_savings - commitment
        savings_maintainable = savings_shortfall == 0

    failed_checks: list[StressCheck] = []
    reasons = list(rate_reasons)
    if not dsr_within_limit:
        failed_checks.append(StressCheck.SAFE_DSR)
        reasons.append(
            f"예상 DSR {expected_dsr * 100:.2f}%가 서비스 안전기준 "
            f"{payload.safe_dsr * 100:.2f}%를 초과합니다."
        )
    if not buffer_maintained:
        failed_checks.append(StressCheck.CASH_BUFFER)
        reasons.append(f"월 최소 Buffer 대비 {abs(buffer_margin):,.0f}원이 부족합니다.")
    if savings_maintainable is False:
        failed_checks.append(StressCheck.SAVINGS_PLAN)
        assert savings_shortfall is not None
        reasons.append(f"현재 적금 계획을 유지하려면 월 {savings_shortfall:,.0f}원이 부족합니다.")

    if failed_checks:
        status = StressScenarioStatus.FAIL
    elif missing_inputs:
        status = StressScenarioStatus.UNKNOWN
        reasons.append("월 적금 계획 금액을 확인해야 전체 스트레스 판정을 확정할 수 있습니다.")
    else:
        status = StressScenarioStatus.PASS
        reasons.append("안전 DSR, 월 Buffer와 적금 납입 계획을 모두 유지할 수 있습니다.")

    return StressScenarioResult(
        scenario=scenario,
        status=status,
        applied_annual_rate=applied_rate,
        stressed_annual_income=stressed_annual_income,
        stressed_monthly_income=stressed_monthly_income,
        stressed_monthly_expense=stressed_monthly_expense,
        stressed_monthly_essential_expense=stressed_essential_expense,
        monthly_payment=monthly_payment,
        monthly_payment_increase=monthly_payment - base_payment,
        expected_dsr=expected_dsr,
        safe_dsr=payload.safe_dsr,
        cashflow_before_savings=cashflow_before_savings,
        buffer_target=buffer_target,
        buffer_margin=buffer_margin,
        monthly_savings_commitment=commitment,
        sustainable_monthly_savings=sustainable_savings,
        savings_shortfall=savings_shortfall,
        cashflow_after_savings=cashflow_after_savings,
        dsr_within_limit=dsr_within_limit,
        buffer_maintained=buffer_maintained,
        savings_plan_maintainable=savings_maintainable,
        failed_checks=tuple(failed_checks),
        missing_inputs=_dedupe(missing_inputs),
        reasons=_dedupe(reasons),
    )


def run_stress_test(payload: StressTestInput) -> StressTestResult:
    """명시된 모든 시나리오를 실행하고 최악 지표와 처리 개수를 집계한다."""

    scenarios = tuple(
        evaluate_stress_scenario(payload, scenario)
        for scenario in payload.scenarios
    )
    pass_count = sum(result.status is StressScenarioStatus.PASS for result in scenarios)
    fail_count = sum(result.status is StressScenarioStatus.FAIL for result in scenarios)
    unknown_count = sum(result.status is StressScenarioStatus.UNKNOWN for result in scenarios)
    if fail_count:
        status = StressScenarioStatus.FAIL
    elif unknown_count:
        status = StressScenarioStatus.UNKNOWN
    else:
        status = StressScenarioStatus.PASS

    dsr_values = tuple(
        result.expected_dsr
        for result in scenarios
        if result.expected_dsr is not None
    )
    buffer_margins = tuple(
        result.buffer_margin
        for result in scenarios
        if result.buffer_margin is not None
    )
    savings_shortfalls = tuple(
        result.savings_shortfall
        for result in scenarios
        if result.savings_shortfall is not None
    )
    first_failed = next(
        (
            result.scenario.code
            for result in scenarios
            if result.status is StressScenarioStatus.FAIL
        ),
        None,
    )
    reasons: list[str] = [
        f"시나리오 {len(scenarios)}개 중 PASS {pass_count}, "
        f"FAIL {fail_count}, UNKNOWN {unknown_count}"
    ]
    if first_failed is not None:
        reasons.append(f"입력 순서상 최초 실패 시나리오는 {first_failed}입니다.")
    if unknown_count:
        reasons.append("UNKNOWN 시나리오의 결측값을 확인해야 전체 위험도를 확정할 수 있습니다.")

    return StressTestResult(
        status=status,
        as_of=payload.as_of,
        scenarios=scenarios,
        pass_count=pass_count,
        fail_count=fail_count,
        unknown_count=unknown_count,
        pass_ratio=Decimal(pass_count) / Decimal(len(scenarios)),
        first_failed_scenario=first_failed,
        maximum_dsr=max(dsr_values) if dsr_values else None,
        minimum_buffer_margin=min(buffer_margins) if buffer_margins else None,
        maximum_savings_shortfall=max(savings_shortfalls) if savings_shortfalls else None,
        scope_notes=payload.scope_notes,
        reasons=tuple(reasons),
    )
