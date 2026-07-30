from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.engines.cashflow import (
    CashflowCondition,
    CashflowEngineStatus,
    CashflowInput,
    PlannedExpense,
    SafeValueBasis,
    calculate_cashflow,
)

_AS_OF = date(2026, 7, 30)


def _complete_input(**overrides: object) -> CashflowInput:
    defaults: dict[str, object] = {
        "as_of": _AS_OF,
        "current_monthly_income": Decimal("3000000"),
        "current_monthly_essential_expense": Decimal("1000000"),
        "monthly_debt_payment": Decimal(0),
        "liquid_assets": Decimal("10000000"),
        "current_emergency_reserve": Decimal("3000000"),
        "income_history": (Decimal("3000000"),) * 6,
        "essential_expense_history": (Decimal("1000000"),) * 6,
        "irregular_essential_expenses": (Decimal("2000000"),),
        "planned_expenses": (
            PlannedExpense(
                name="예정지출",
                amount=Decimal("1200000"),
                months_until_due=12,
            ),
        ),
        "family_medical_risk": Decimal(0),
        "emergency_build_months": 12,
    }
    defaults.update(overrides)
    return CashflowInput(**defaults)  # type: ignore[arg-type]


def test_complete_case_calculates_all_three_stages() -> None:
    result = calculate_cashflow(_complete_input())

    assert result.status is CashflowEngineStatus.COMPLETE
    assert result.diagnosis.income_basis is SafeValueBasis.PERCENTILE
    assert result.diagnosis.expense_basis is SafeValueBasis.PERCENTILE
    assert result.diagnosis.safe_monthly_surplus == Decimal("2000000")
    assert result.diagnosis.cashflow_buffer_target == Decimal("300000")
    assert result.diagnosis.condition is CashflowCondition.SURPLUS

    assert result.risk.risk_index == 0
    assert result.risk.emergency_months == Decimal("3")
    assert result.emergency_fund.target_amount == Decimal("3000000")
    assert result.emergency_fund.shortfall_amount == 0
    assert result.emergency_fund.usable_liquid_assets_after_target == Decimal("7000000")

    assert result.allocation.planned_expense_monthly_reserve == Decimal("100000")
    assert result.allocation.available_before_emergency_contribution == Decimal("1600000")
    assert result.allocation.emergency_fund_monthly_contribution == 0
    assert result.allocation.monthly_housing_savings_available == Decimal("1600000")
    assert result.missing_inputs == ()


def test_short_history_uses_current_values_and_reports_partial_quality() -> None:
    payload = CashflowInput(
        as_of=_AS_OF,
        current_monthly_income=Decimal("2000000"),
        current_monthly_essential_expense=Decimal("1000000"),
        monthly_debt_payment=Decimal("100000"),
        liquid_assets=Decimal("3000000"),
        current_emergency_reserve=Decimal("1000000"),
    )

    result = calculate_cashflow(payload)

    assert result.status is CashflowEngineStatus.PARTIAL
    assert result.diagnosis.income_basis is SafeValueBasis.CURRENT_INPUT
    assert result.diagnosis.expense_basis is SafeValueBasis.CURRENT_INPUT
    assert "monthly_income_history" in result.missing_inputs
    assert "monthly_essential_expense_history" in result.missing_inputs
    assert "family_medical_risk" in result.missing_inputs
    assert "irregular_essential_expenses" in result.missing_inputs
    assert "planned_expenses" in result.missing_inputs
    assert result.allocation.monthly_housing_savings_available is not None


def test_three_to_five_month_history_uses_recent_average() -> None:
    result = calculate_cashflow(
        _complete_input(
            income_history=(
                Decimal("2000000"),
                Decimal("3000000"),
                Decimal("4000000"),
            ),
            essential_expense_history=(
                Decimal("900000"),
                Decimal("1000000"),
                Decimal("1100000"),
            ),
        )
    )

    assert result.diagnosis.income_basis is SafeValueBasis.RECENT_AVERAGE
    assert result.diagnosis.expense_basis is SafeValueBasis.RECENT_AVERAGE
    assert result.diagnosis.safe_monthly_income == Decimal("3000000")
    assert result.diagnosis.safe_monthly_essential_expense == Decimal("1000000")


def test_missing_current_emergency_reserve_does_not_become_zero() -> None:
    result = calculate_cashflow(_complete_input(current_emergency_reserve=None))

    assert result.status is CashflowEngineStatus.PARTIAL
    assert result.emergency_fund.current_amount is None
    assert result.emergency_fund.shortfall_amount is None
    assert result.emergency_fund.required_monthly_contribution is None
    assert result.allocation.emergency_fund_monthly_contribution is None
    assert result.allocation.monthly_housing_savings_available is None
    assert "current_emergency_reserve" in result.missing_inputs


def test_emergency_contribution_is_capped_by_actual_cashflow() -> None:
    result = calculate_cashflow(
        _complete_input(
            current_monthly_income=Decimal("2000000"),
            income_history=(Decimal("2000000"),) * 6,
            current_emergency_reserve=Decimal(0),
            planned_expenses=(),
            emergency_build_months=3,
        )
    )

    assert result.emergency_fund.target_amount == Decimal("3000000")
    assert result.emergency_fund.required_monthly_contribution == Decimal("1000000")
    assert result.allocation.available_before_emergency_contribution == Decimal("700000")
    assert result.emergency_fund.affordable_monthly_contribution == Decimal("700000")
    assert result.emergency_fund.effective_build_months == 5
    assert result.allocation.monthly_housing_savings_available == 0


def test_deficit_is_preserved_and_allocations_stay_non_negative() -> None:
    result = calculate_cashflow(
        _complete_input(
            current_monthly_income=Decimal("1000000"),
            current_monthly_essential_expense=Decimal("1200000"),
            income_history=(Decimal("1000000"),) * 6,
            essential_expense_history=(Decimal("1200000"),) * 6,
            current_emergency_reserve=Decimal(0),
            planned_expenses=(),
        )
    )

    assert result.diagnosis.safe_monthly_surplus == Decimal("-200000")
    assert result.diagnosis.condition is CashflowCondition.DEFICIT
    assert result.allocation.available_before_emergency_contribution == 0
    assert result.allocation.emergency_fund_monthly_contribution == 0
    assert result.allocation.monthly_housing_savings_available == 0


def test_higher_essential_expense_never_increases_housing_savings() -> None:
    baseline = calculate_cashflow(_complete_input(planned_expenses=()))
    higher_expense = calculate_cashflow(
        _complete_input(
            current_monthly_essential_expense=Decimal("1500000"),
            essential_expense_history=(Decimal("1500000"),) * 6,
            planned_expenses=(),
        )
    )

    assert (
        higher_expense.allocation.monthly_housing_savings_available
        <= baseline.allocation.monthly_housing_savings_available
    )


def test_higher_debt_payment_never_increases_housing_savings() -> None:
    baseline = calculate_cashflow(_complete_input(planned_expenses=()))
    higher_debt = calculate_cashflow(
        _complete_input(
            monthly_debt_payment=Decimal("500000"),
            planned_expenses=(),
        )
    )

    assert (
        higher_debt.allocation.monthly_housing_savings_available
        <= baseline.allocation.monthly_housing_savings_available
    )


def test_higher_current_reserve_never_increases_emergency_shortfall() -> None:
    baseline_payload = _complete_input(
        current_emergency_reserve=Decimal("1000000"),
        planned_expenses=(),
    )
    baseline = calculate_cashflow(baseline_payload)
    higher_reserve = calculate_cashflow(
        replace(
            baseline_payload,
            current_emergency_reserve=Decimal("2000000"),
        )
    )

    assert (
        higher_reserve.emergency_fund.shortfall_amount <= baseline.emergency_fund.shortfall_amount
    )


def test_higher_family_risk_never_reduces_emergency_target() -> None:
    lower_risk = calculate_cashflow(
        _complete_input(
            family_medical_risk=Decimal(0),
            planned_expenses=(),
        )
    )
    higher_risk = calculate_cashflow(
        _complete_input(
            family_medical_risk=Decimal(1),
            planned_expenses=(),
        )
    )

    assert higher_risk.risk.risk_index >= lower_risk.risk.risk_index
    assert higher_risk.emergency_fund.target_amount >= lower_risk.emergency_fund.target_amount


def test_current_emergency_reserve_cannot_exceed_liquid_assets() -> None:
    with pytest.raises(ValueError, match="liquid_assets"):
        _complete_input(
            liquid_assets=Decimal("1000000"),
            current_emergency_reserve=Decimal("2000000"),
        )


def test_income_and_expense_histories_must_cover_the_same_period() -> None:
    with pytest.raises(ValueError, match="같은 기간"):
        _complete_input(
            income_history=(Decimal("3000000"),) * 6,
            essential_expense_history=(Decimal("1000000"),) * 5,
        )
