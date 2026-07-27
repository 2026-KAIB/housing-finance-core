from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 적금 #10, regulatory_review_no
# "준법감시인 심의필 제2026-1395-2호"). join_member="만 19세 이상 실명의 개인
# (1인 1계좌), 개인사업자/임의단체/공동명의 불가" — 다른 KB 적금과 달리 개인사업자를
# 명시적으로 배제한다. spcl_cnd(최근 1년 무거래 우대이율)는 우대금리 조건이라 제외.


def _is_individual(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type == "individual"


KB_STAR_SAVINGS_3_PACK = ProductRulePack(
    product_name="KB 스타적금 III",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2026-1395-2호",
    effective_start_date=date(2026, 4, 13),
    effective_end_date=date(2027, 3, 31),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_STAR_SAVINGS_3_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="만 19세 이상만 가입할 수 있습니다.",
        ),
        PredicateRule(
            code="KB_STAR_SAVINGS_3_MEMBER_ELIGIBILITY",
            predicate=_is_individual,
            failure_reason="개인사업자·임의단체·공동명의는 가입할 수 없습니다.",
            required_fields=("applicant_type",),
        ),
        ComparisonRule(
            code="KB_STAR_SAVINGS_3_MONTHLY_PAYMENT_RANGE",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(10_000, 300_000),
            failure_reason="월 저축금은 1만원 이상 30만원 이하여야 합니다.",
        ),
    ),
)
