from dataclasses import dataclass
from datetime import date

from app.rule_engine.common.applicant import ApplicantEligibilityCriteria, ApplicantSnapshot
from app.rule_engine.policy.schemas import PolicyProduct


@dataclass(frozen=True)
class PolicyEligibilityContext:
    """정책상품 자격 판정에 필요한 사용자·시나리오 스냅샷."""

    as_of: date
    applicant: ApplicantSnapshot
    product: PolicyProduct

    @property
    def eligibility_criteria(self) -> ApplicantEligibilityCriteria:
        return self.product.eligibility

    @property
    def data_version(self) -> str:
        return self.product.data_version
