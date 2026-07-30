"""현금흐름·비상자금·목적별 자금배분의 계층 간 불변 계약."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def _require_unit_interval(value: Decimal | None, name: str) -> None:
    if value is not None and not Decimal(0) <= value <= Decimal(1):
        raise ValueError(f"{name}은(는) 0 이상 1 이하여야 합니다.")


class CashflowEngineStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class CashflowCondition(StrEnum):
    SURPLUS = "SURPLUS"
    BUFFER_SHORTFALL = "BUFFER_SHORTFALL"
    DEFICIT = "DEFICIT"


class SafeValueBasis(StrEnum):
    PERCENTILE = "PERCENTILE"
    RECENT_AVERAGE = "RECENT_AVERAGE"
    CURRENT_INPUT = "CURRENT_INPUT"


@dataclass(frozen=True)
class PlannedExpense:
    amount: Decimal
    months_until_due: int
    name: str | None = None

    def __post_init__(self) -> None:
        _require_non_negative(self.amount, "amount")
        if self.months_until_due <= 0:
            raise ValueError("months_until_due은(는) 0보다 커야 합니다.")
        if self.name is not None and not self.name.strip():
            raise ValueError("예정지출 이름은 공백일 수 없습니다.")


@dataclass(frozen=True)
class CashflowInput:
    """검증된 현재 금융 스냅샷과 선택적 월별 이력."""

    as_of: date
    current_monthly_income: Decimal
    current_monthly_essential_expense: Decimal
    monthly_debt_payment: Decimal = Decimal(0)
    liquid_assets: Decimal = Decimal(0)
    current_emergency_reserve: Decimal | None = None

    income_history: tuple[Decimal, ...] = ()
    essential_expense_history: tuple[Decimal, ...] = ()
    irregular_essential_expenses: tuple[Decimal, ...] | None = None
    planned_expenses: tuple[PlannedExpense, ...] | None = None

    income_volatility_risk_override: Decimal | None = None
    expense_volatility_risk_override: Decimal | None = None
    debt_burden_risk_override: Decimal | None = None
    family_medical_risk: Decimal | None = None
    emergency_build_months: int | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name, value in (
            ("current_monthly_income", self.current_monthly_income),
            ("current_monthly_essential_expense", self.current_monthly_essential_expense),
            ("monthly_debt_payment", self.monthly_debt_payment),
            ("liquid_assets", self.liquid_assets),
        ):
            _require_non_negative(value, name)
        if self.current_emergency_reserve is not None:
            _require_non_negative(
                self.current_emergency_reserve,
                "current_emergency_reserve",
            )
            if self.current_emergency_reserve > self.liquid_assets:
                raise ValueError("current_emergency_reserve는 liquid_assets를 초과할 수 없습니다.")
        for name, values in (
            ("income_history", self.income_history),
            ("essential_expense_history", self.essential_expense_history),
            ("irregular_essential_expenses", self.irregular_essential_expenses or ()),
        ):
            if any(value < 0 for value in values):
                raise ValueError(f"{name}에는 음수를 넣을 수 없습니다.")
        if (
            self.income_history
            and self.essential_expense_history
            and len(self.income_history) != len(self.essential_expense_history)
        ):
            raise ValueError("소득 이력과 필수지출 이력은 같은 기간이어야 합니다.")
        for name, value in (
            ("income_volatility_risk_override", self.income_volatility_risk_override),
            ("expense_volatility_risk_override", self.expense_volatility_risk_override),
            ("debt_burden_risk_override", self.debt_burden_risk_override),
            ("family_medical_risk", self.family_medical_risk),
        ):
            _require_unit_interval(value, name)
        if self.emergency_build_months is not None and self.emergency_build_months <= 0:
            raise ValueError("emergency_build_months은(는) 0보다 커야 합니다.")


@dataclass(frozen=True)
class CashflowDiagnosis:
    income_basis: SafeValueBasis
    expense_basis: SafeValueBasis
    safe_monthly_income: Decimal
    safe_monthly_essential_expense: Decimal
    monthly_debt_payment: Decimal
    safe_monthly_surplus: Decimal
    cashflow_buffer_target: Decimal
    condition: CashflowCondition
    income_coefficient_of_variation: Decimal | None
    expense_coefficient_of_variation: Decimal | None


@dataclass(frozen=True)
class RiskAssessment:
    income_volatility_risk: Decimal
    expense_volatility_risk: Decimal
    debt_burden_risk: Decimal
    family_medical_risk: Decimal
    risk_index: Decimal
    emergency_months: Decimal
    defaulted_components: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmergencyFundPlan:
    monthly_expense_basis_amount: Decimal
    irregular_expense_percentile_amount: Decimal | None
    target_amount: Decimal
    current_amount: Decimal | None
    shortfall_amount: Decimal | None
    target_build_months: int
    required_monthly_contribution: Decimal | None
    affordable_monthly_contribution: Decimal | None
    effective_build_months: int | None
    protected_liquid_assets: Decimal
    usable_liquid_assets_after_target: Decimal


@dataclass(frozen=True)
class BudgetAllocation:
    planned_expense_monthly_reserve: Decimal
    available_before_emergency_contribution: Decimal
    emergency_fund_monthly_contribution: Decimal | None
    monthly_housing_savings_available: Decimal | None


@dataclass(frozen=True)
class CashflowResult:
    as_of: date
    status: CashflowEngineStatus
    diagnosis: CashflowDiagnosis
    risk: RiskAssessment
    emergency_fund: EmergencyFundPlan
    allocation: BudgetAllocation
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()
