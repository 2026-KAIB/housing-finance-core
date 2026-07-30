"""안전소득·비상자금·목적별 자금배분을 계산하는 결정론적 순수 엔진."""

from decimal import ROUND_CEILING, Decimal

from app.engines.cashflow.formulas import (
    arithmetic_mean,
    coefficient_of_variation,
    emergency_fund_shortfall,
    emergency_fund_target,
    emergency_months,
    normalize_to_unit_interval,
    percentile,
    planned_expense_monthly_reserve,
    required_monthly_contribution,
    safe_monthly_surplus,
    weighted_risk_index,
)
from app.engines.cashflow.models import (
    BudgetAllocation,
    CashflowCondition,
    CashflowDiagnosis,
    CashflowEngineStatus,
    CashflowInput,
    CashflowResult,
    EmergencyFundPlan,
    RiskAssessment,
    SafeValueBasis,
)
from app.engines.cashflow.policy import (
    DEFAULT_CASHFLOW_POLICY,
    CashflowPolicy,
)
from app.engines.safety import cashflow_buffer


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _resolve_safe_value(
    *,
    history: tuple[Decimal, ...],
    current_value: Decimal,
    percentile_probability: Decimal,
    history_name: str,
    policy: CashflowPolicy,
    assumptions: list[str],
    missing_inputs: list[str],
) -> tuple[Decimal, SafeValueBasis]:
    if len(history) >= policy.minimum_history_months_for_percentile:
        return (
            percentile(history, percentile_probability),
            SafeValueBasis.PERCENTILE,
        )
    if len(history) >= policy.minimum_history_months_for_average:
        assumptions.append(f"{history_name}가 {len(history)}개월뿐이어서 최근 평균을 사용했습니다.")
        return arithmetic_mean(history), SafeValueBasis.RECENT_AVERAGE

    missing_inputs.append(history_name)
    assumptions.append(f"{history_name}가 부족하여 현재 입력값을 사용했습니다.")
    return current_value, SafeValueBasis.CURRENT_INPUT


def _resolve_volatility_risk(
    *,
    history: tuple[Decimal, ...],
    override: Decimal | None,
    full_risk_value: Decimal,
    component_name: str,
    policy: CashflowPolicy,
    missing_inputs: list[str],
    assumptions: list[str],
) -> tuple[Decimal, Decimal | None, bool]:
    if len(history) >= policy.minimum_history_months_for_percentile:
        coefficient = coefficient_of_variation(history)
        if coefficient is not None:
            return (
                normalize_to_unit_interval(coefficient, full_risk_value),
                coefficient,
                False,
            )
        assumptions.append(f"{component_name} 평균이 0이어서 변동계수를 계산하지 못했습니다.")
    if override is not None:
        assumptions.append(f"{component_name}는 검증된 외부 위험점수를 사용했습니다.")
        return override, None, False

    missing_inputs.append(component_name)
    assumptions.append(
        f"{component_name}가 없어 정책 중립값 {policy.missing_risk_component}을 적용했습니다."
    )
    return policy.missing_risk_component, None, True


def _effective_build_months(
    *,
    shortfall_amount: Decimal,
    affordable_monthly_contribution: Decimal,
) -> int | None:
    if shortfall_amount == 0:
        return 0
    if affordable_monthly_contribution == 0:
        return None
    return int(
        (shortfall_amount / affordable_monthly_contribution).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def calculate_cashflow(
    payload: CashflowInput,
    *,
    policy: CashflowPolicy = DEFAULT_CASHFLOW_POLICY,
) -> CashflowResult:
    """현금흐름 진단, 비상자금 계획, 주택자금 배분을 순서대로 계산한다."""

    assumptions = list(payload.assumptions)
    missing_inputs: list[str] = []
    reasons: list[str] = []

    safe_income, income_basis = _resolve_safe_value(
        history=payload.income_history,
        current_value=payload.current_monthly_income,
        percentile_probability=policy.safe_income_percentile,
        history_name="monthly_income_history",
        policy=policy,
        assumptions=assumptions,
        missing_inputs=missing_inputs,
    )
    safe_expense, expense_basis = _resolve_safe_value(
        history=payload.essential_expense_history,
        current_value=payload.current_monthly_essential_expense,
        percentile_probability=policy.safe_expense_percentile,
        history_name="monthly_essential_expense_history",
        policy=policy,
        assumptions=assumptions,
        missing_inputs=missing_inputs,
    )

    surplus = safe_monthly_surplus(
        safe_monthly_income=safe_income,
        safe_monthly_essential_expense=safe_expense,
        monthly_debt_payment=payload.monthly_debt_payment,
    )
    buffer_target = cashflow_buffer(
        safe_expense,
        floor=policy.buffer_floor,
        ratio=policy.buffer_ratio,
    )
    if surplus < 0:
        condition = CashflowCondition.DEFICIT
        reasons.append("필수지출과 기존 대출상환 후 월 현금흐름이 적자입니다.")
    elif surplus < buffer_target:
        condition = CashflowCondition.BUFFER_SHORTFALL
        reasons.append("월 잉여자금이 최소 현금흐름 여유자금보다 작습니다.")
    else:
        condition = CashflowCondition.SURPLUS
        reasons.append("필수지출·기존 부채상환 후 최소 현금흐름 여유를 유지합니다.")

    income_risk, income_cv, income_defaulted = _resolve_volatility_risk(
        history=payload.income_history,
        override=payload.income_volatility_risk_override,
        full_risk_value=policy.income_cv_full_risk,
        component_name="income_volatility_risk",
        policy=policy,
        missing_inputs=missing_inputs,
        assumptions=assumptions,
    )
    expense_risk, expense_cv, expense_defaulted = _resolve_volatility_risk(
        history=payload.essential_expense_history,
        override=payload.expense_volatility_risk_override,
        full_risk_value=policy.expense_cv_full_risk,
        component_name="expense_volatility_risk",
        policy=policy,
        missing_inputs=missing_inputs,
        assumptions=assumptions,
    )

    if payload.debt_burden_risk_override is not None:
        debt_risk = payload.debt_burden_risk_override
        debt_defaulted = False
        assumptions.append("부채부담은 검증된 외부 위험점수를 사용했습니다.")
    else:
        debt_ratio = (
            payload.monthly_debt_payment / safe_income
            if safe_income > 0
            else (Decimal(1) if payload.monthly_debt_payment > 0 else Decimal(0))
        )
        debt_risk = normalize_to_unit_interval(
            debt_ratio,
            policy.debt_burden_full_risk_ratio,
        )
        debt_defaulted = False

    if payload.family_medical_risk is None:
        family_risk = policy.missing_risk_component
        family_defaulted = True
        missing_inputs.append("family_medical_risk")
        assumptions.append(
            f"가족·의료위험 정보가 없어 정책 중립값 {policy.missing_risk_component}을 적용했습니다."
        )
    else:
        family_risk = payload.family_medical_risk
        family_defaulted = False

    risk_index = weighted_risk_index(
        income_volatility_risk=income_risk,
        expense_volatility_risk=expense_risk,
        debt_burden_risk=debt_risk,
        family_medical_risk=family_risk,
        policy=policy,
    )
    required_emergency_months = emergency_months(risk_index, policy)
    defaulted_components = tuple(
        name
        for name, is_defaulted in (
            ("income_volatility_risk", income_defaulted),
            ("expense_volatility_risk", expense_defaulted),
            ("debt_burden_risk", debt_defaulted),
            ("family_medical_risk", family_defaulted),
        )
        if is_defaulted
    )

    if payload.irregular_essential_expenses is None:
        irregular_p95 = None
        missing_inputs.append("irregular_essential_expenses")
        assumptions.append(
            "비정기 필수지출 이력이 없어 월 필수지출 기준으로 비상자금 목표를 계산했습니다."
        )
    elif payload.irregular_essential_expenses:
        irregular_p95 = percentile(
            payload.irregular_essential_expenses,
            Decimal("0.95"),
        )
    else:
        irregular_p95 = None

    target_amount = emergency_fund_target(
        safe_monthly_essential_expense=safe_expense,
        required_months=required_emergency_months,
        irregular_expense_percentile_amount=irregular_p95,
    )
    target_build_months = (
        payload.emergency_build_months
        if payload.emergency_build_months is not None
        else policy.default_emergency_build_months
    )
    if payload.emergency_build_months is None:
        assumptions.append(
            f"비상자금 마련기간은 정책 기본값 {target_build_months}개월을 사용했습니다."
        )

    if payload.planned_expenses is None:
        planned_reserve = Decimal(0)
        missing_inputs.append("planned_expenses")
        assumptions.append("예정지출 정보가 없어 월 예정지출 적립액을 0원으로 계산했습니다.")
    else:
        planned_reserve = planned_expense_monthly_reserve(payload.planned_expenses)

    available_before_emergency = max(
        Decimal(0),
        surplus - buffer_target - planned_reserve,
    )
    protected_liquid_assets = min(payload.liquid_assets, target_amount)
    usable_liquid_assets = max(
        Decimal(0),
        payload.liquid_assets - target_amount,
    )

    if payload.current_emergency_reserve is None:
        shortfall = None
        required_contribution = None
        affordable_contribution = None
        effective_months = None
        housing_savings = None
        missing_inputs.append("current_emergency_reserve")
        reasons.append(
            "현재 비상자금이 없어 부족액과 주택자금 월 저축 가능액을 확정하지 못했습니다."
        )
    else:
        shortfall = emergency_fund_shortfall(
            target_amount=target_amount,
            current_amount=payload.current_emergency_reserve,
        )
        required_contribution = required_monthly_contribution(
            shortfall_amount=shortfall,
            build_months=target_build_months,
        )
        affordable_contribution = min(
            required_contribution,
            available_before_emergency,
        )
        effective_months = _effective_build_months(
            shortfall_amount=shortfall,
            affordable_monthly_contribution=affordable_contribution,
        )
        housing_savings = max(
            Decimal(0),
            available_before_emergency - affordable_contribution,
        )
        if shortfall == 0:
            reasons.append("현재 비상자금이 목표액 이상입니다.")
        else:
            reasons.append("현재 비상자금이 목표액보다 부족합니다.")
        if affordable_contribution < required_contribution:
            reasons.append(
                "현재 현금흐름으로는 정책상 비상자금 마련기간을 맞출 수 없어 "
                "실제 감당 가능한 적립액을 적용했습니다."
            )
        if housing_savings == 0:
            reasons.append(
                "비상자금과 현금흐름 여유를 우선하면 현재 주택자금 월 저축 가능액은 0원입니다."
            )

    status = CashflowEngineStatus.PARTIAL if missing_inputs else CashflowEngineStatus.COMPLETE
    return CashflowResult(
        as_of=payload.as_of,
        status=status,
        diagnosis=CashflowDiagnosis(
            income_basis=income_basis,
            expense_basis=expense_basis,
            safe_monthly_income=safe_income,
            safe_monthly_essential_expense=safe_expense,
            monthly_debt_payment=payload.monthly_debt_payment,
            safe_monthly_surplus=surplus,
            cashflow_buffer_target=buffer_target,
            condition=condition,
            income_coefficient_of_variation=income_cv,
            expense_coefficient_of_variation=expense_cv,
        ),
        risk=RiskAssessment(
            income_volatility_risk=income_risk,
            expense_volatility_risk=expense_risk,
            debt_burden_risk=debt_risk,
            family_medical_risk=family_risk,
            risk_index=risk_index,
            emergency_months=required_emergency_months,
            defaulted_components=defaulted_components,
        ),
        emergency_fund=EmergencyFundPlan(
            monthly_expense_basis_amount=safe_expense,
            irregular_expense_percentile_amount=irregular_p95,
            target_amount=target_amount,
            current_amount=payload.current_emergency_reserve,
            shortfall_amount=shortfall,
            target_build_months=target_build_months,
            required_monthly_contribution=required_contribution,
            affordable_monthly_contribution=affordable_contribution,
            effective_build_months=effective_months,
            protected_liquid_assets=protected_liquid_assets,
            usable_liquid_assets_after_target=usable_liquid_assets,
        ),
        allocation=BudgetAllocation(
            planned_expense_monthly_reserve=planned_reserve,
            available_before_emergency_contribution=available_before_emergency,
            emergency_fund_monthly_contribution=affordable_contribution,
            monthly_housing_savings_available=housing_savings,
        ),
        missing_inputs=_dedupe(missing_inputs),
        reasons=_dedupe(reasons),
        assumptions=_dedupe(assumptions),
        policy_sources=(policy.source, policy.version),
    )
