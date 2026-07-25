from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 적금 #5, regulatory_review_no
# "준법감시인 심의필 제2026-0276-2호"). join_member="실명의 개인(1인 2계좌限),
# 개인사업자 및 서류 미제출 임의단체 가입 가능 (공동명의 불가)" 중 계좌 수·공동명의
# 제약은 판정 불가라 제외. spcl_cnd(패키지/선택 우대금리)는 우대금리 조건이라 제외.


def _is_allowed_member_type(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type in ("individual", "sole_proprietor", "unincorporated_association")


KB_MY_OWN_SAVINGS_PACK = ProductRulePack(
    product_name="KB 나만의 적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2026-0276-2호",
    effective_start_date=date(2026, 1, 26),
    effective_end_date=date(2027, 12, 31),
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_MY_OWN_SAVINGS_MEMBER_ELIGIBILITY",
            predicate=_is_allowed_member_type,
            failure_reason="실명의 개인, 개인사업자 또는 임의단체만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
        ComparisonRule(
            code="KB_MY_OWN_SAVINGS_MONTHLY_PAYMENT_RANGE",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(10_000, 1_000_000),
            failure_reason="월 저축금은 1만원 이상 100만원 이하여야 합니다.",
        ),
    ),
)
