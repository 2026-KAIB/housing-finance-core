"""Pure formulas backed by the versioned purchase-cost policy."""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.engines.purchase_costs.policy import BrokerageBracket, PurchaseCostPolicy


def floor_won(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("money value must not be negative")
    return value.quantize(Decimal("1"), rounding=ROUND_DOWN)


def acquisition_tax_rate(
    purchase_price: Decimal,
    *,
    policy: PurchaseCostPolicy,
) -> Decimal:
    """Standard individual housing rate from Local Tax Act article 11(1)(8)."""

    if purchase_price <= 0:
        raise ValueError("purchase_price must be greater than zero")
    if purchase_price <= policy.lower_acquisition_price_limit:
        return policy.lower_acquisition_tax_rate
    if purchase_price > policy.upper_acquisition_price_limit:
        return policy.upper_acquisition_tax_rate

    percentage_points = (purchase_price * Decimal(2) / Decimal("300000000") - Decimal(3)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return percentage_points / Decimal(100)


def local_education_tax_rate(
    standard_acquisition_tax_rate: Decimal,
    *,
    policy: PurchaseCostPolicy,
) -> Decimal:
    if standard_acquisition_tax_rate < 0:
        raise ValueError("standard_acquisition_tax_rate must not be negative")
    return standard_acquisition_tax_rate * policy.local_education_tax_multiplier


def resolve_national_housing_scale(
    exclusive_area_m2: Decimal | None,
    *,
    override: bool | None,
) -> bool | None:
    """Resolve only area ranges that are identical in every Korean region.

    Up to 85㎡ is always within the national scale and above 100㎡ is always
    outside it. The 85–100㎡ range depends on whether the home is in a qualifying
    non-capital eup/myeon area, so it remains unknown without an override.
    """

    if override is not None:
        return override
    if exclusive_area_m2 is None:
        return None
    if exclusive_area_m2 <= Decimal(85):
        return True
    if exclusive_area_m2 > Decimal(100):
        return False
    return None


def brokerage_fee_upper_bound(
    purchase_price: Decimal,
    *,
    brackets: tuple[BrokerageBracket, ...],
) -> tuple[Decimal, Decimal, Decimal | None]:
    if purchase_price <= 0:
        raise ValueError("purchase_price must be greater than zero")
    for bracket in brackets:
        if bracket.upper_bound_exclusive is None or purchase_price < bracket.upper_bound_exclusive:
            calculated = floor_won(purchase_price * bracket.rate)
            if bracket.fee_cap is not None:
                calculated = min(calculated, bracket.fee_cap)
            return calculated, bracket.rate, bracket.fee_cap
    raise ValueError("brokerage brackets must end with an open bracket")
