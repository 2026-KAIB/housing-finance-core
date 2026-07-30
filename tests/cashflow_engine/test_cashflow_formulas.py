from decimal import Decimal

import pytest

from app.engines.cashflow.formulas import (
    coefficient_of_variation,
    emergency_fund_shortfall,
    emergency_fund_target,
    percentile,
    planned_expense_monthly_reserve,
    safe_monthly_surplus,
)
from app.engines.cashflow.models import PlannedExpense


def test_percentile_uses_decimal_linear_interpolation() -> None:
    result = percentile(
        (
            Decimal("100"),
            Decimal("200"),
            Decimal("300"),
            Decimal("400"),
        ),
        Decimal("0.25"),
    )

    assert result == Decimal("175.00")


def test_coefficient_of_variation_is_zero_for_stable_values() -> None:
    result = coefficient_of_variation((Decimal("100"), Decimal("100"), Decimal("100")))

    assert result == 0


def test_coefficient_of_variation_is_unknown_when_mean_is_zero() -> None:
    assert coefficient_of_variation((Decimal(0), Decimal(0))) is None


def test_safe_surplus_preserves_a_deficit_instead_of_clamping_it() -> None:
    result = safe_monthly_surplus(
        safe_monthly_income=Decimal("1000000"),
        safe_monthly_essential_expense=Decimal("900000"),
        monthly_debt_payment=Decimal("200000"),
    )

    assert result == Decimal("-100000")


def test_emergency_target_uses_the_larger_of_monthly_and_irregular_bases() -> None:
    result = emergency_fund_target(
        safe_monthly_essential_expense=Decimal("1000000"),
        required_months=Decimal("3"),
        irregular_expense_percentile_amount=Decimal("5000000"),
    )

    assert result == Decimal("5000000")


def test_emergency_shortfall_never_becomes_negative() -> None:
    result = emergency_fund_shortfall(
        target_amount=Decimal("3000000"),
        current_amount=Decimal("5000000"),
    )

    assert result == 0


def test_planned_expenses_are_converted_to_monthly_reserves() -> None:
    result = planned_expense_monthly_reserve(
        (
            PlannedExpense(
                name="등록금",
                amount=Decimal("1200000"),
                months_until_due=12,
            ),
            PlannedExpense(
                name="보험료",
                amount=Decimal("600000"),
                months_until_due=6,
            ),
        )
    )

    assert result == Decimal("200000")


@pytest.mark.parametrize(
    ("values", "probability"),
    [
        ((), Decimal("0.5")),
        ((Decimal("1"),), Decimal("-0.1")),
        ((Decimal("1"),), Decimal("1.1")),
    ],
)
def test_percentile_rejects_invalid_inputs(
    values: tuple[Decimal, ...],
    probability: Decimal,
) -> None:
    with pytest.raises(ValueError):
        percentile(values, probability)
