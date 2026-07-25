from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import PredicateRule

# 원문(selected_23_products.json 주택담보대출 #1, regulatory_review_no
# "준법감시인 심의필 제2026-1803-2호"). join_member는 "주택을 담보로 대출 신청하는
# 고객"이라는 상품 정의일 뿐 판정 가능한 신청자격이 아니라 규칙화하지 않는다.
# loan_lmt("담보조사가격 및 소득금액 등에 따른 대출가능금액")는 감정평가 의존
# 자유텍스트라 파싱 불가 — data_pipeline이 손대지 않고 그대로 둔다.
# etc_note의 "40년 초과 만34세 이하만 가능"만 유일하게 판정 가능한 조건이다.
# spcl_cnd(실적연동/전자계약/취약차주 우대금리)는 우대금리 조건이라 제외.


def _long_term_requires_young_age(facts: Mapping[str, object]) -> bool | None:
    loan_term_years = facts.get("loan_term_years")
    age = facts.get("age")
    if loan_term_years is None:
        return None
    if loan_term_years <= 40:
        return True
    if age is None:
        return None
    return age <= 34


KB_MORTGAGE_LOAN_PACK = ProductRulePack(
    product_name="KB 주택담보대출",
    category=ProductCategory.MORTGAGE_LOAN,
    version="준법감시인 심의필 제2026-1803-2호",
    effective_start_date=date(2026, 4, 21),
    effective_end_date=date(2027, 12, 31),
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_MORTGAGE_LONG_TERM_AGE_LIMIT",
            predicate=_long_term_requires_young_age,
            failure_reason="대출기간이 40년을 초과하는 분할상환은 만 34세 이하만 가능합니다.",
            required_fields=("loan_term_years",),
        ),
    ),
)
