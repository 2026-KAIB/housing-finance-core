from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.rule_engine.common.applicant import ApplicantEligibilityCriteria


@dataclass(frozen=True)
class LoanProduct:
    """대출상품 데이터 관리 항목 (DESIGN SSOT §20 / 부록 B).

    `effective_end_date=None`은 종료일 미정(현재 유효)을 뜻한다.

    `loan_limit`/`max_ltv`/`max_dti`/`max_dsr`은 원천 데이터에 정제된 숫자로
    존재하지 않는 경우가 흔하다(대출한도는 자유텍스트, LTV·DTI·DSR은 상품
    데이터가 아닌 별도 규제 상수표에서 옴). 파싱·매칭 실패 시 `None`으로 두고
    임의 숫자로 대체하지 않는다(부록 B-5) — 해당 값이 없으면 관련 규칙은
    "판정 불가"로 보고 통과시킨다(신청자 결격이 아니라 데이터 공백이므로).
    """

    product_id: str
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
    source_type: str = "api"
    regulatory_review_no: str | None = None
    regulatory_review_date: date | None = None

    @property
    def data_version(self) -> str:
        if self.regulatory_review_no:
            return f"{self.product_id}@{self.regulatory_review_no}"
        return f"{self.product_id}@{self.confirmed_date.isoformat()}"
