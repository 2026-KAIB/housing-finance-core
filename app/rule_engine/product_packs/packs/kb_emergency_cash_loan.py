from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 개인신용대출 #3, regulatory_review_no
# "준법감시인 심의필 제 2024-4942-43호"). join_member="서울보증보험(주)의
# 개인금융신용보험증권 발급가능한 만19세 이상 내국인". loan_lmt="최소 50만원 ~
# 최대 300만원". spcl_cnd(한도소진율 우대금리)는 우대금리 조건이라 제외.


def _not_foreigner(facts: Mapping[str, object]) -> bool | None:
    is_foreigner = facts.get("is_foreigner")
    if is_foreigner is None:
        return None
    return not is_foreigner


KB_EMERGENCY_CASH_LOAN_PACK = ProductRulePack(
    product_name="KB 비상금대출",
    category=ProductCategory.CREDIT_LOAN,
    version="준법감시인 심의필 제 2024-4942-43호",
    effective_start_date=date(2024, 10, 17),
    effective_end_date=date(2026, 9, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_EMERGENCY_CASH_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="만 19세 이상만 신청할 수 있습니다.",
        ),
        PredicateRule(
            code="KB_EMERGENCY_CASH_NOT_FOREIGNER",
            predicate=_not_foreigner,
            failure_reason="내국인만 신청할 수 있습니다.",
            required_fields=("is_foreigner",),
        ),
        ComparisonRule(
            code="KB_EMERGENCY_CASH_AMOUNT_RANGE",
            field_name="requested_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(500_000, 3_000_000),
            failure_reason="대출금액은 50만원 이상 300만원 이내여야 합니다.",
        ),
    ),
)
