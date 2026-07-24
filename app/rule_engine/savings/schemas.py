from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class SavingsProduct:
    """예·적금상품 데이터 관리 항목 (DESIGN SSOT §20).

    `effective_end_date=None`은 종료일 미정(현재 유효)을 뜻한다.
    """

    product_id: str
    name: str
    operating_institution: str
    effective_start_date: date
    effective_end_date: date | None
    confirmed_date: date
    source_url: str
    min_monthly_payment: Decimal
    max_monthly_payment: Decimal
    maturity_months: int
    is_principal_protected: bool
    is_deposit_protected: bool

    @property
    def data_version(self) -> str:
        return f"{self.product_id}@{self.confirmed_date.isoformat()}"
