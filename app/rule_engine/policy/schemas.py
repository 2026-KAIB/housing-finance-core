from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rule_engine.common.applicant import ApplicantEligibilityCriteria


@dataclass(frozen=True)
class PolicyProduct:
    """정책 데이터 관리 항목 (DESIGN SSOT §20).

    `effective_end_date=None`은 종료일 미정(현재 유효)을 뜻한다.
    """

    policy_id: str
    name: str
    operating_institution: str
    effective_start_date: date
    effective_end_date: date | None
    confirmed_date: date
    source_url: str
    eligibility: ApplicantEligibilityCriteria
    loan_limit: Decimal | None = None
    max_ltv: Decimal | None = None
    max_dti: Decimal | None = None
    max_dsr: Decimal | None = None

    @property
    def data_version(self) -> str:
        return f"{self.policy_id}@{self.confirmed_date.isoformat()}"
