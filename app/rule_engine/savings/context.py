from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rule_engine.savings.schemas import SavingsProduct


@dataclass(frozen=True)
class SavingsEligibilityContext:
    """예·적금 필터링 컨텍스트 (DESIGN SSOT §11.1).

    회사별 예상 예치액·우대조건 달성가능 여부는 포트폴리오·상품평가 엔진이
    먼저 산출한 값을 그대로 받는다(Rule Engine은 판정만 한다).
    """

    as_of: date
    product: SavingsProduct
    is_membership_eligible: bool
    planned_monthly_payment: Decimal
    fund_needed_date: date
    product_maturity_date: date
    accepts_principal_risk: bool
    projected_deposit_at_institution: Decimal
    deposit_protection_limit: Decimal
    preferential_conditions_feasible: bool

    @property
    def data_version(self) -> str:
        return self.product.data_version
