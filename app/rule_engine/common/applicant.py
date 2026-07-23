from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ApplicantSnapshot:
    """신청자격 판정에 필요한 사용자·목표 스냅샷 (DESIGN SSOT §13.1-1,2)."""

    age: int
    annual_income: Decimal
    is_married: bool
    is_first_home_buyer: bool
    region_code: str | None
    target_price: Decimal
    target_area_m2: Decimal | None


@dataclass(frozen=True)
class ApplicantEligibilityCriteria:
    """정책·대출상품이 공통으로 갖는 신청자격 조건 (DESIGN SSOT §13.1-1,2 / §20).

    값이 `None`/`False`인 항목은 해당 조건이 없음을 의미한다.
    """

    min_age: int | None = None
    max_age: int | None = None
    max_annual_income: Decimal | None = None
    max_annual_income_married: Decimal | None = None
    requires_first_home_buyer: bool = False
    requires_married: bool | None = None
    allowed_region_codes: tuple[str, ...] | None = None
    max_target_price: Decimal | None = None
    max_target_area_m2: Decimal | None = None
