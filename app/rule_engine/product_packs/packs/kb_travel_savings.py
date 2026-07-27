from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 적금 #8, regulatory_review_no
# "준법감시인 심의필 제2026-1763-2호"). join_member="실명의 개인 (1인 1계좌)" 중
# 계좌 수 제약은 판정 불가라 제외. spcl_cnd(여행친구/오픈뱅킹/자동이체 우대이율)와
# 연계서비스(여행상품 쿠폰)는 가입조건이 아니라 제외.


def _is_individual(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type == "individual"


KB_TRAVEL_SAVINGS_PACK = ProductRulePack(
    product_name="KB 두근두근여행적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2026-1763-2호",
    effective_start_date=date(2026, 5, 26),
    effective_end_date=date(2028, 4, 30),
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_TRAVEL_SAVINGS_MEMBER_ELIGIBILITY",
            predicate=_is_individual,
            failure_reason="실명의 개인만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
        ComparisonRule(
            code="KB_TRAVEL_SAVINGS_MONTHLY_PAYMENT_RANGE",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(50_000, 1_000_000),
            failure_reason="월 저축금은 5만원 이상 100만원 이하여야 합니다.",
        ),
    ),
)
