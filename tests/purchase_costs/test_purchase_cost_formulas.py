from decimal import Decimal

import pytest

from app.engines.purchase_costs.formulas import (
    acquisition_tax_rate,
    brokerage_fee_upper_bound,
    floor_won,
    local_education_tax_rate,
    resolve_national_housing_scale,
)
from app.engines.purchase_costs.policy import DEFAULT_PURCHASE_COST_POLICY

_POLICY = DEFAULT_PURCHASE_COST_POLICY


@pytest.mark.parametrize(
    ("purchase_price", "expected_rate"),
    [
        ("600000000", "0.01"),
        ("700000000", "0.016667"),
        ("750000000", "0.02"),
        ("900000000", "0.03"),
        ("900000001", "0.03"),
    ],
)
def test_standard_acquisition_tax_rate_boundaries(
    purchase_price: str,
    expected_rate: str,
) -> None:
    assert acquisition_tax_rate(
        Decimal(purchase_price),
        policy=_POLICY,
    ) == Decimal(expected_rate)


def test_local_education_tax_is_ten_percent_of_standard_housing_rate() -> None:
    assert local_education_tax_rate(
        Decimal("0.016667"),
        policy=_POLICY,
    ) == Decimal("0.0016667")


@pytest.mark.parametrize(
    ("purchase_price", "expected_fee", "expected_rate", "expected_cap"),
    [
        ("49999999", "250000", "0.006", "250000"),
        ("50000000", "250000", "0.005", "800000"),
        ("199999999", "800000", "0.005", "800000"),
        ("200000000", "800000", "0.004", None),
        ("899999999", "3599999", "0.004", None),
        ("900000000", "4500000", "0.005", None),
        ("1500000000", "10500000", "0.007", None),
    ],
)
def test_housing_brokerage_upper_bound_brackets(
    purchase_price: str,
    expected_fee: str,
    expected_rate: str,
    expected_cap: str | None,
) -> None:
    fee, rate, cap = brokerage_fee_upper_bound(
        Decimal(purchase_price),
        brackets=_POLICY.brokerage_brackets,
    )

    assert fee == Decimal(expected_fee)
    assert rate == Decimal(expected_rate)
    assert cap == (Decimal(expected_cap) if expected_cap is not None else None)


@pytest.mark.parametrize(
    ("area", "override", "expected"),
    [
        ("85", None, True),
        ("85.01", None, None),
        ("100", None, None),
        ("100.01", None, False),
        ("90", True, True),
        ("90", False, False),
        (None, None, None),
    ],
)
def test_national_housing_scale_is_only_inferred_when_region_cannot_change_it(
    area: str | None,
    override: bool | None,
    expected: bool | None,
) -> None:
    assert (
        resolve_national_housing_scale(
            Decimal(area) if area is not None else None,
            override=override,
        )
        is expected
    )


def test_money_estimates_floor_fractional_won() -> None:
    assert floor_won(Decimal("123.99")) == Decimal("123")
    with pytest.raises(ValueError, match="negative"):
        floor_won(Decimal("-0.01"))
