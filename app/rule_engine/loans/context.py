from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rule_engine.common.applicant import ApplicantEligibilityCriteria, ApplicantSnapshot
from app.rule_engine.loans.schemas import LoanProduct


@dataclass(frozen=True)
class LoanEligibilityContext:
    """대출 필수조건 판정 컨텍스트 (DESIGN SSOT §13.1).

    LTV·DTI·DSR, 자기자본, 구매 후 현금흐름은 대출·현금흐름 계산 엔진이 먼저
    산출한 값을 그대로 받는다(Rule Engine은 판정만 한다).
    """

    as_of: date
    applicant: ApplicantSnapshot
    product: LoanProduct
    requested_loan_amount: Decimal
    computed_ltv: Decimal
    computed_dti: Decimal
    computed_dsr: Decimal
    equity_available: Decimal
    equity_target: Decimal
    buffer_target: Decimal
    post_purchase_monthly_cashflow: Decimal
    post_purchase_emergency_fund: Decimal

    @property
    def eligibility_criteria(self) -> ApplicantEligibilityCriteria:
        return self.product.eligibility

    @property
    def data_version(self) -> str:
        return self.product.data_version
