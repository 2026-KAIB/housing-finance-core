"""Versioned legal thresholds used by the purchase-cost estimator."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class BrokerageBracket:
    upper_bound_exclusive: Decimal | None
    rate: Decimal
    fee_cap: Decimal | None = None

    def __post_init__(self) -> None:
        if self.upper_bound_exclusive is not None and self.upper_bound_exclusive <= 0:
            raise ValueError("brokerage upper bound must be greater than zero")
        if self.rate < 0:
            raise ValueError("brokerage rate must not be negative")
        if self.fee_cap is not None and self.fee_cap < 0:
            raise ValueError("brokerage fee cap must not be negative")


@dataclass(frozen=True)
class PurchaseCostPolicy:
    version: str = "purchase-cost-policy/2026-07-01"
    effective_start: date = date(2026, 7, 1)
    verified_through: date = date(2026, 12, 31)

    lower_acquisition_price_limit: Decimal = Decimal("600000000")
    upper_acquisition_price_limit: Decimal = Decimal("900000000")
    lower_acquisition_tax_rate: Decimal = Decimal("0.01")
    upper_acquisition_tax_rate: Decimal = Decimal("0.03")
    local_education_tax_multiplier: Decimal = Decimal("0.10")
    rural_special_tax_rate: Decimal = Decimal("0.002")

    brokerage_vat_rate: Decimal = Decimal("0.10")
    brokerage_brackets: tuple[BrokerageBracket, ...] = (
        BrokerageBracket(
            upper_bound_exclusive=Decimal("50000000"),
            rate=Decimal("0.006"),
            fee_cap=Decimal("250000"),
        ),
        BrokerageBracket(
            upper_bound_exclusive=Decimal("200000000"),
            rate=Decimal("0.005"),
            fee_cap=Decimal("800000"),
        ),
        BrokerageBracket(
            upper_bound_exclusive=Decimal("900000000"),
            rate=Decimal("0.004"),
        ),
        BrokerageBracket(
            upper_bound_exclusive=Decimal("1200000000"),
            rate=Decimal("0.005"),
        ),
        BrokerageBracket(
            upper_bound_exclusive=Decimal("1500000000"),
            rate=Decimal("0.006"),
        ),
        BrokerageBracket(
            upper_bound_exclusive=None,
            rate=Decimal("0.007"),
        ),
    )
    sources: tuple[str, ...] = (
        "지방세법 제11조·제151조 (시행 2026-07-01)",
        "농어촌특별세법 제4조·제5조 및 같은 법 시행령 제4조",
        "공인중개사법 시행규칙 제20조 별표 1",
    )

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("policy version must not be blank")
        if self.effective_start > self.verified_through:
            raise ValueError("effective_start must not exceed verified_through")
        for name, value in (
            ("lower_acquisition_price_limit", self.lower_acquisition_price_limit),
            ("upper_acquisition_price_limit", self.upper_acquisition_price_limit),
            ("lower_acquisition_tax_rate", self.lower_acquisition_tax_rate),
            ("upper_acquisition_tax_rate", self.upper_acquisition_tax_rate),
            ("local_education_tax_multiplier", self.local_education_tax_multiplier),
            ("rural_special_tax_rate", self.rural_special_tax_rate),
            ("brokerage_vat_rate", self.brokerage_vat_rate),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.lower_acquisition_price_limit >= self.upper_acquisition_price_limit:
            raise ValueError("acquisition price limits must be strictly increasing")
        if not Decimal(0) <= self.brokerage_vat_rate <= Decimal(1):
            raise ValueError("brokerage_vat_rate must be between zero and one")
        bounds = [
            bracket.upper_bound_exclusive
            for bracket in self.brokerage_brackets
            if bracket.upper_bound_exclusive is not None
        ]
        if bounds != sorted(bounds) or len(bounds) + 1 != len(self.brokerage_brackets):
            raise ValueError("brokerage brackets must be ordered and end with an open bracket")
        if self.brokerage_brackets[-1].upper_bound_exclusive is not None:
            raise ValueError("last brokerage bracket must not have an upper bound")
        if not self.sources:
            raise ValueError("policy sources must not be empty")

    def supports(self, as_of: date) -> bool:
        return self.effective_start <= as_of <= self.verified_through


DEFAULT_PURCHASE_COST_POLICY = PurchaseCostPolicy()
