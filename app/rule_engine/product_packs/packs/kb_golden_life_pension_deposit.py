from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(`예금 리스트 4개.txt` #1, verified_at 2026-07-23, source_type=manual_pdf,
# regulatory_review_no="준법감시인 심의필 제2026-3320-4호", effective_period 명시값 사용).
# join_member의 실명 여부는 상위 사용자 정규화 단계에서 확인하고 이 Pack은 정규화된
# applicant_type만 받는다. 개인사업자와 임의단체는 원문에서 명시적으로 가입 가능하다.
# 연금수령·금리우대쿠폰은 우대금리 조건, 판매한도는 실시간 상품상태, 가입기간별 금리는
# optionList이므로 가입 필수조건 Pack에서 제외하고 handoff를 통해 예적금 엔진에 전달한다.
# 추가입금 불가와 만기후 이율도 가입자격이 아닌 상품 이용·계산 조건이라 여기서 판정하지 않는다.


def _is_allowed_member_type(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type in (
        "individual",
        "sole_proprietor",
        "unincorporated_association",
    )


KB_GOLDEN_LIFE_PENSION_DEPOSIT_PACK = ProductRulePack(
    product_name="KB골든라이프연금예금",
    category=ProductCategory.TERM_DEPOSIT,
    version="준법감시인 심의필 제2026-3320-4호",
    effective_start_date=date(2026, 7, 21),
    effective_end_date=date(2028, 6, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_GOLDEN_LIFE_PD_MIN_DEPOSIT_AMOUNT",
            field_name="deposit_amount",
            operator=ComparisonOperator.GTE,
            expected=1_000_000,
            failure_reason="가입금액은 1백만원 이상이어야 합니다.",
        ),
        PredicateRule(
            code="KB_GOLDEN_LIFE_PD_MEMBER_ELIGIBILITY",
            predicate=_is_allowed_member_type,
            failure_reason="실명의 개인, 개인사업자 또는 임의단체만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
    ),
)
