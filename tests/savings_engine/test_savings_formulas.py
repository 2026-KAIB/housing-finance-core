from decimal import Decimal

import pytest

from app.engines.savings.formulas import (
    expected_annual_rate,
    installment_savings_gross_maturity,
    interest_tax,
    monthly_effective_rate,
    term_deposit_gross_maturity,
)
from app.engines.savings.models import ContributionTiming, InterestType


def test_expected_rate_interpolates_with_bonus_probability() -> None:
    assert expected_annual_rate(
        annual_base_rate=Decimal("0.03"),
        annual_max_rate=Decimal("0.05"),
        bonus_achievement_probability=Decimal("0.25"),
    ) == Decimal("0.035")


def test_twelve_month_compound_deposit_matches_annual_effective_rate() -> None:
    maturity = term_deposit_gross_maturity(
        principal=Decimal("10000000"),
        annual_rate=Decimal("0.03"),
        months=12,
        interest_type=InterestType.COMPOUND,
    )

    assert abs(maturity - Decimal("10300000")) < Decimal("0.000001")
    assert monthly_effective_rate(Decimal("0.03")) != Decimal("0.03") / Decimal(12)


def test_simple_installment_beginning_has_one_more_interest_month_per_payment() -> None:
    beginning = installment_savings_gross_maturity(
        monthly_payment=Decimal("1000000"),
        annual_rate=Decimal("0.03"),
        months=12,
        interest_type=InterestType.SIMPLE,
        contribution_timing=ContributionTiming.BEGINNING,
    )
    end = installment_savings_gross_maturity(
        monthly_payment=Decimal("1000000"),
        annual_rate=Decimal("0.03"),
        months=12,
        interest_type=InterestType.SIMPLE,
        contribution_timing=ContributionTiming.END,
    )

    assert beginning - end == Decimal("30000")


def test_compound_installment_matches_design_golden_value() -> None:
    maturity = installment_savings_gross_maturity(
        monthly_payment=Decimal("1000000"),
        annual_rate=Decimal("0.03"),
        months=60,
        interest_type=InterestType.COMPOUND,
        contribution_timing=ContributionTiming.END,
    )

    assert abs(maturity - Decimal("64580962")) < Decimal("1")


def test_interest_tax_is_explicit_and_not_hard_coded() -> None:
    assert interest_tax(
        gross_interest=Decimal("1000000"),
        tax_rate=Decimal("0.154"),
    ) == Decimal("154000.000")


def test_invalid_bonus_probability_is_rejected() -> None:
    with pytest.raises(ValueError, match="0 이상 1 이하"):
        expected_annual_rate(
            annual_base_rate=Decimal("0.03"),
            annual_max_rate=Decimal("0.05"),
            bonus_achievement_probability=Decimal("1.1"),
        )
