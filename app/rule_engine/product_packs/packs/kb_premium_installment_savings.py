from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 적금 #2, regulatory_review_no
# "준법감시인 심의필 제2024-5171-14호"). join_member="실명의 개인 (1인 1계좌)" 중
# "1인 1계좌"는 계좌 개수 제약이라 판정 불가(추측 금지) — 실명 개인 여부만 판정.
# spcl_cnd(단체가입/나라사랑/쿠폰/교차거래 우대이율)는 우대금리 조건이라 제외.

_MONTHLY_RANGE = (10_000, 3_000_000)


def _is_individual(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type == "individual"


KB_PREMIUM_INSTALLMENT_SAVINGS_PACK = ProductRulePack(
    product_name="KB 국민프리미엄적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2024-5171-14호",
    effective_start_date=date(2024, 11, 13),
    effective_end_date=date(2026, 9, 30),
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_PREMIUM_SAVINGS_MEMBER_ELIGIBILITY",
            predicate=_is_individual,
            failure_reason="실명의 개인만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
        ComparisonRule(
            code="KB_PREMIUM_SAVINGS_MONTHLY_PAYMENT_RANGE",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=_MONTHLY_RANGE,
            failure_reason="회차별 저축금은 1만원 이상 매월 3백만원 이내여야 합니다.",
        ),
    ),
)
