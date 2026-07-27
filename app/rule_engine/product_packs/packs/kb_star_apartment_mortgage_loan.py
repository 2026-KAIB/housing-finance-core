from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 주택담보대출 #3, regulatory_review_no
# "준법감시인 심의필 제2026-1803-9호"). join_member="... 소득확인 가능고객
# (미성년자, 외국인 등 제외)" -> 성년(19세 이상)·내국인만 인코딩(담보 명의 등은
# 판정 불가). loan_lmt="최소 1천만원 이상 최대 10억원 이내"는 그대로 파싱 가능.
# etc_note "40년 초과 만34세 이하만 가능"은 KB 주택담보대출과 동일 패턴.
# spcl_cnd(전자계약/취약차주 우대금리)는 우대금리 조건이라 제외.


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


def _not_foreigner(facts: Mapping[str, object]) -> bool | None:
    is_foreigner = facts.get("is_foreigner")
    if is_foreigner is None:
        return None
    return not is_foreigner


KB_STAR_APARTMENT_MORTGAGE_LOAN_PACK = ProductRulePack(
    product_name="KB스타 아파트담보대출(주택자금)",
    category=ProductCategory.MORTGAGE_LOAN,
    version="준법감시인 심의필 제2026-1803-9호",
    effective_start_date=date(2026, 4, 21),
    effective_end_date=date(2027, 12, 31),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_STAR_APT_MORTGAGE_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="미성년자는 신청할 수 없습니다 (만 19세 이상).",
        ),
        PredicateRule(
            code="KB_STAR_APT_MORTGAGE_NOT_FOREIGNER",
            predicate=_not_foreigner,
            failure_reason="외국인은 신청할 수 없습니다.",
            required_fields=("is_foreigner",),
        ),
        ComparisonRule(
            code="KB_STAR_APT_MORTGAGE_AMOUNT_RANGE",
            field_name="requested_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(10_000_000, 1_000_000_000),
            failure_reason="대출금액은 1천만원 이상 10억원 이내여야 합니다.",
        ),
        PredicateRule(
            code="KB_STAR_APT_MORTGAGE_LONG_TERM_AGE_LIMIT",
            predicate=_long_term_requires_young_age,
            failure_reason="대출기간이 40년을 초과하는 경우 만 34세 이하만 가능합니다.",
            required_fields=("loan_term_years",),
        ),
    ),
)
