from decimal import Decimal

import pytest

from app.engines.savings.calculator import calculate_savings
from app.engines.savings.models import (
    ContributionTiming,
    InterestType,
    SavingsCalculationInput,
    SavingsProductKind,
)


def test_deposit_calculation_returns_taxed_maturity_amount() -> None:
    result = calculate_savings(
        SavingsCalculationInput(
            product_name="테스트 정기예금",
            product_kind=SavingsProductKind.TERM_DEPOSIT,
            term_months=12,
            interest_type=InterestType.SIMPLE,
            annual_base_rate=Decimal("0.03"),
            annual_max_rate=Decimal("0.05"),
            bonus_achievement_probability=Decimal("0.5"),
            tax_rate=Decimal("0.154"),
            deposit_amount=Decimal("10000000"),
        )
    )

    assert result.expected_annual_rate == Decimal("0.040")
    assert result.total_principal == Decimal("10000000")
    assert result.gross_interest == Decimal("400000.000")
    assert result.tax_amount == Decimal("61600.000000")
    assert result.maturity_amount == Decimal("10338400.000000")
    assert abs(result.annualized_net_return_rate - Decimal("0.03384")) < Decimal(
        "0.0000000001"
    )


def test_installment_requires_contribution_timing() -> None:
    payload = SavingsCalculationInput(
        product_name="테스트 적금",
        product_kind=SavingsProductKind.INSTALLMENT_SAVINGS,
        term_months=12,
        interest_type=InterestType.SIMPLE,
        annual_base_rate=Decimal("0.03"),
        annual_max_rate=Decimal("0.03"),
        bonus_achievement_probability=Decimal("0"),
        tax_rate=Decimal("0.154"),
        monthly_payment_amount=Decimal("500000"),
    )

    with pytest.raises(ValueError, match="contribution_timing"):
        calculate_savings(payload)


def test_product_kinds_cannot_consume_each_others_amount_field() -> None:
    payload = SavingsCalculationInput(
        product_name="테스트 정기예금",
        product_kind=SavingsProductKind.TERM_DEPOSIT,
        term_months=12,
        interest_type=InterestType.SIMPLE,
        annual_base_rate=Decimal("0.03"),
        annual_max_rate=Decimal("0.03"),
        bonus_achievement_probability=Decimal("0"),
        tax_rate=Decimal("0.154"),
        deposit_amount=Decimal("10000000"),
        monthly_payment_amount=Decimal("500000"),
        contribution_timing=ContributionTiming.BEGINNING,
    )

    with pytest.raises(ValueError, match="monthly_payment_amount"):
        calculate_savings(payload)
