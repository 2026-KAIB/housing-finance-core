"""Input and output contracts for a conservative purchase-cost estimate."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


class PurchaseCostEngineStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    POLICY_OUT_OF_RANGE = "POLICY_OUT_OF_RANGE"


class CostComponentStatus(StrEnum):
    ESTIMATED = "ESTIMATED"
    PROVIDED = "PROVIDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PurchaseCostInput:
    """Facts needed by the supported individual, standard one-home scenario.

    ``household_home_count_after_purchase`` is the household count including the
    property being evaluated. Unknown legal classifications remain ``None`` and
    are never treated as a favorable default.
    """

    as_of: date
    purchase_price: Decimal
    buyer_is_corporation: bool | None = None
    household_home_count_after_purchase: int | None = None
    is_registered_housing: bool | None = None
    is_luxury_home: bool | None = None
    exclusive_area_m2: Decimal | None = None
    is_national_housing_scale_override: bool | None = None
    registration_and_legal_costs: Decimal | None = None
    brokerage_vat_rate_override: Decimal | None = None

    def __post_init__(self) -> None:
        if self.purchase_price <= 0:
            raise ValueError("purchase_price must be greater than zero")
        if self.household_home_count_after_purchase is not None:
            if self.household_home_count_after_purchase <= 0:
                raise ValueError("household_home_count_after_purchase must be greater than zero")
        if self.exclusive_area_m2 is not None and self.exclusive_area_m2 <= 0:
            raise ValueError("exclusive_area_m2 must be greater than zero")
        if self.registration_and_legal_costs is not None:
            _require_non_negative(
                self.registration_and_legal_costs,
                "registration_and_legal_costs",
            )
        if self.brokerage_vat_rate_override is not None and not (
            Decimal(0) <= self.brokerage_vat_rate_override <= Decimal(1)
        ):
            raise ValueError("brokerage_vat_rate_override must be between zero and one")
        if self.is_registered_housing is False and self.is_national_housing_scale_override is True:
            raise ValueError("non-housing property cannot be marked as national housing scale")


@dataclass(frozen=True)
class CostComponent:
    code: str
    status: CostComponentStatus
    amount: Decimal | None
    rate: Decimal | None = None
    basis: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("component code must not be blank")
        if self.status is CostComponentStatus.UNKNOWN:
            if self.amount is not None:
                raise ValueError("UNKNOWN component must not contain an amount")
        elif self.amount is None:
            raise ValueError("known component must contain an amount")
        if self.amount is not None:
            _require_non_negative(self.amount, "component amount")
        if self.rate is not None:
            _require_non_negative(self.rate, "component rate")


@dataclass(frozen=True)
class PurchaseCostResult:
    as_of: date
    policy_version: str
    status: PurchaseCostEngineStatus
    purchase_price: Decimal
    acquisition_tax: CostComponent
    local_education_tax: CostComponent
    rural_special_tax: CostComponent
    brokerage_fee_upper_bound: CostComponent
    brokerage_vat: CostComponent
    registration_and_legal_costs: CostComponent
    known_ancillary_costs: Decimal
    minimum_total_purchase_cost: Decimal
    total_ancillary_costs: Decimal | None
    total_purchase_cost: Decimal | None
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        _require_non_negative(self.purchase_price, "purchase_price")
        _require_non_negative(self.known_ancillary_costs, "known_ancillary_costs")
        if self.minimum_total_purchase_cost != (self.purchase_price + self.known_ancillary_costs):
            raise ValueError("minimum_total_purchase_cost must equal price plus known costs")
        if (self.total_ancillary_costs is None) != (self.total_purchase_cost is None):
            raise ValueError("total cost fields must both be known or both be unknown")
        if self.total_ancillary_costs is not None:
            _require_non_negative(
                self.total_ancillary_costs,
                "total_ancillary_costs",
            )
            if self.total_purchase_cost != (self.purchase_price + self.total_ancillary_costs):
                raise ValueError("total_purchase_cost must equal price plus ancillary costs")
        if self.status is PurchaseCostEngineStatus.COMPLETE and self.total_purchase_cost is None:
            raise ValueError("COMPLETE result must contain a total purchase cost")
