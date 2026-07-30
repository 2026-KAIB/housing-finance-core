from datetime import date
from decimal import Decimal

import pytest

from app.engines.purchase_costs import (
    CostComponent,
    CostComponentStatus,
    PurchaseCostEngineStatus,
    PurchaseCostInput,
    estimate_purchase_costs,
)

_AS_OF = date(2026, 7, 30)


def _standard_request(**overrides: object) -> PurchaseCostInput:
    values: dict[str, object] = {
        "as_of": _AS_OF,
        "purchase_price": Decimal("500000000"),
        "buyer_is_corporation": False,
        "household_home_count_after_purchase": 1,
        "is_registered_housing": True,
        "is_luxury_home": False,
        "exclusive_area_m2": Decimal("59"),
        "registration_and_legal_costs": Decimal("1000000"),
    }
    values.update(overrides)
    return PurchaseCostInput(**values)  # type: ignore[arg-type]


def test_supported_one_home_purchase_produces_a_complete_conservative_total() -> None:
    result = estimate_purchase_costs(_standard_request())

    assert result.status is PurchaseCostEngineStatus.COMPLETE
    assert result.policy_version == "purchase-cost-policy/2026-07-01"
    assert result.acquisition_tax.amount == Decimal("5000000")
    assert result.acquisition_tax.rate == Decimal("0.01")
    assert result.local_education_tax.amount == Decimal("500000")
    assert result.rural_special_tax.status is CostComponentStatus.NOT_APPLICABLE
    assert result.rural_special_tax.amount == Decimal(0)
    assert result.brokerage_fee_upper_bound.amount == Decimal("2000000")
    assert result.brokerage_vat.amount == Decimal("200000")
    assert result.registration_and_legal_costs.amount == Decimal("1000000")
    assert result.known_ancillary_costs == Decimal("8700000")
    assert result.total_ancillary_costs == Decimal("8700000")
    assert result.total_purchase_cost == Decimal("508700000")
    assert result.missing_inputs == ()
    assert any("감면 전" in note for note in result.assumptions)
    assert any("상한" in note for note in result.assumptions)


def test_missing_registration_quote_keeps_a_minimum_but_not_a_final_total() -> None:
    result = estimate_purchase_costs(_standard_request(registration_and_legal_costs=None))

    assert result.status is PurchaseCostEngineStatus.PARTIAL
    assert result.known_ancillary_costs == Decimal("7700000")
    assert result.minimum_total_purchase_cost == Decimal("507700000")
    assert result.total_ancillary_costs is None
    assert result.total_purchase_cost is None
    assert "registration_and_legal_costs" in result.missing_inputs


def test_area_over_national_scale_adds_rural_special_tax() -> None:
    result = estimate_purchase_costs(_standard_request(exclusive_area_m2=Decimal("101")))

    assert result.status is PurchaseCostEngineStatus.COMPLETE
    assert result.rural_special_tax.amount == Decimal("1000000")
    assert result.rural_special_tax.rate == Decimal("0.002")
    assert result.total_purchase_cost == Decimal("509700000")


def test_ambiguous_85_to_100_square_metre_area_remains_partial() -> None:
    result = estimate_purchase_costs(_standard_request(exclusive_area_m2=Decimal("90")))

    assert result.status is PurchaseCostEngineStatus.PARTIAL
    assert result.rural_special_tax.amount is None
    assert "is_national_housing_scale" in result.missing_inputs
    assert result.total_purchase_cost is None

    resolved = estimate_purchase_costs(
        _standard_request(
            exclusive_area_m2=Decimal("90"),
            is_national_housing_scale_override=False,
        )
    )
    assert resolved.status is PurchaseCostEngineStatus.COMPLETE
    assert resolved.rural_special_tax.amount == Decimal("1000000")


def test_missing_tax_facts_are_not_replaced_with_single_home_defaults() -> None:
    result = estimate_purchase_costs(
        PurchaseCostInput(
            as_of=_AS_OF,
            purchase_price=Decimal("500000000"),
            is_registered_housing=True,
            exclusive_area_m2=Decimal("59"),
        )
    )

    assert result.status is PurchaseCostEngineStatus.PARTIAL
    assert result.acquisition_tax.amount is None
    assert result.local_education_tax.amount is None
    assert result.brokerage_fee_upper_bound.amount == Decimal("2000000")
    assert set(result.missing_inputs) >= {
        "buyer_is_corporation",
        "household_home_count_after_purchase",
        "is_luxury_home",
        "registration_and_legal_costs",
    }


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"buyer_is_corporation": True}, "법인"),
        ({"household_home_count_after_purchase": 2}, "일반 1주택 외"),
        ({"is_registered_housing": False}, "주택으로 확인되지 않은"),
        ({"is_luxury_home": True}, "고급주택"),
    ],
)
def test_out_of_scope_tax_cases_are_explicitly_unsupported(
    overrides: dict[str, object],
    reason_fragment: str,
) -> None:
    result = estimate_purchase_costs(_standard_request(**overrides))

    assert result.status is PurchaseCostEngineStatus.UNSUPPORTED
    assert result.acquisition_tax.amount is None
    assert any(reason_fragment in reason for reason in result.reasons)


def test_policy_out_of_verified_range_calculates_nothing() -> None:
    result = estimate_purchase_costs(_standard_request(as_of=date(2027, 1, 1)))

    assert result.status is PurchaseCostEngineStatus.POLICY_OUT_OF_RANGE
    assert result.known_ancillary_costs == 0
    assert result.minimum_total_purchase_cost == Decimal("500000000")
    assert result.total_purchase_cost is None
    assert result.missing_inputs == ("purchase_cost_policy",)


def test_input_and_component_contracts_reject_contradictions() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        _standard_request(purchase_price=Decimal(0))
    with pytest.raises(ValueError, match="national housing scale"):
        _standard_request(
            is_registered_housing=False,
            is_national_housing_scale_override=True,
        )
    with pytest.raises(ValueError, match="UNKNOWN"):
        CostComponent(
            code="invalid",
            status=CostComponentStatus.UNKNOWN,
            amount=Decimal(0),
        )
