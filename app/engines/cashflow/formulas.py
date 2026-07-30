"""현금흐름·비상자금 엔진의 결정론적 순수 공식."""

from decimal import Decimal

from app.engines.cashflow.models import PlannedExpense
from app.engines.cashflow.policy import CashflowPolicy


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def arithmetic_mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("평균을 계산할 값이 필요합니다.")
    if any(value < 0 for value in values):
        raise ValueError("평균 입력값에는 음수를 넣을 수 없습니다.")
    return sum(values, Decimal(0)) / Decimal(len(values))


def percentile(values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    """정렬된 표본의 선형보간 분위값을 Decimal 정밀도로 계산한다."""

    if not values:
        raise ValueError("분위값을 계산할 값이 필요합니다.")
    if any(value < 0 for value in values):
        raise ValueError("분위값 입력에는 음수를 넣을 수 없습니다.")
    if not Decimal(0) <= probability <= Decimal(1):
        raise ValueError("probability는 0 이상 1 이하여야 합니다.")

    ordered = tuple(sorted(values))
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def coefficient_of_variation(values: tuple[Decimal, ...]) -> Decimal | None:
    """모집단 표준편차 ÷ 평균. 평균이 0이면 정의되지 않아 ``None``이다."""

    mean = arithmetic_mean(values)
    if mean == 0:
        return None
    variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(len(values))
    return variance.sqrt() / mean


def normalize_to_unit_interval(value: Decimal, full_risk_value: Decimal) -> Decimal:
    _require_non_negative(value, "value")
    if full_risk_value <= 0:
        raise ValueError("full_risk_value은(는) 0보다 커야 합니다.")
    return min(Decimal(1), value / full_risk_value)


def safe_monthly_surplus(
    *,
    safe_monthly_income: Decimal,
    safe_monthly_essential_expense: Decimal,
    monthly_debt_payment: Decimal,
) -> Decimal:
    for name, value in (
        ("safe_monthly_income", safe_monthly_income),
        ("safe_monthly_essential_expense", safe_monthly_essential_expense),
        ("monthly_debt_payment", monthly_debt_payment),
    ):
        _require_non_negative(value, name)
    return safe_monthly_income - safe_monthly_essential_expense - monthly_debt_payment


def weighted_risk_index(
    *,
    income_volatility_risk: Decimal,
    expense_volatility_risk: Decimal,
    debt_burden_risk: Decimal,
    family_medical_risk: Decimal,
    policy: CashflowPolicy,
) -> Decimal:
    components = (
        income_volatility_risk,
        expense_volatility_risk,
        debt_burden_risk,
        family_medical_risk,
    )
    if any(not Decimal(0) <= component <= Decimal(1) for component in components):
        raise ValueError("위험지수 구성요소는 0 이상 1 이하여야 합니다.")
    return (
        policy.income_volatility_weight * income_volatility_risk
        + policy.expense_volatility_weight * expense_volatility_risk
        + policy.debt_burden_weight * debt_burden_risk
        + policy.family_medical_weight * family_medical_risk
    )


def emergency_months(risk_index: Decimal, policy: CashflowPolicy) -> Decimal:
    if not Decimal(0) <= risk_index <= Decimal(1):
        raise ValueError("risk_index는 0 이상 1 이하여야 합니다.")
    return policy.emergency_base_months + policy.emergency_extra_months * risk_index


def emergency_fund_target(
    *,
    safe_monthly_essential_expense: Decimal,
    required_months: Decimal,
    irregular_expense_percentile_amount: Decimal | None,
) -> Decimal:
    _require_non_negative(
        safe_monthly_essential_expense,
        "safe_monthly_essential_expense",
    )
    _require_non_negative(required_months, "required_months")
    if irregular_expense_percentile_amount is not None:
        _require_non_negative(
            irregular_expense_percentile_amount,
            "irregular_expense_percentile_amount",
        )
    recurring_basis = safe_monthly_essential_expense * required_months
    return max(recurring_basis, irregular_expense_percentile_amount or Decimal(0))


def emergency_fund_shortfall(
    *,
    target_amount: Decimal,
    current_amount: Decimal,
) -> Decimal:
    _require_non_negative(target_amount, "target_amount")
    _require_non_negative(current_amount, "current_amount")
    return max(Decimal(0), target_amount - current_amount)


def required_monthly_contribution(
    *,
    shortfall_amount: Decimal,
    build_months: int,
) -> Decimal:
    _require_non_negative(shortfall_amount, "shortfall_amount")
    if build_months <= 0:
        raise ValueError("build_months은(는) 0보다 커야 합니다.")
    return shortfall_amount / Decimal(build_months)


def planned_expense_monthly_reserve(
    planned_expenses: tuple[PlannedExpense, ...],
) -> Decimal:
    return sum(
        (expense.amount / Decimal(expense.months_until_due) for expense in planned_expenses),
        Decimal(0),
    )
