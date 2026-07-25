from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 전세자금대출 #3, regulatory_review_no
# "준법감시인 심의필 제2026-1803-14호"). join_member="만 19세 이상 성년 세대주 ...
# (금융비용부담율 40% 이내, 무주택 또는 1주택)". "금융비용부담율"은 상품 고유의
# 사전 계산값을 그대로 받는다 — 계산 방법 자체는 이 Pack의 책임이 아니다.
# loan_lmt="최소 5백만원 이상 최대 5억원 이하 (임차보증금액의 80% 이내, 1주택자
# 최대 3억원 이내, 규제지역 1주택자 2억원 제한)" 중 임차보증금 80% 조건은 별도
# 필드가 필요해 이번 1차 판정에서는 정액 한도만 판정한다. spcl_cnd(전자계약/취약차주
# 우대금리)는 우대금리 조건이라 제외.


def _loan_amount_within_tier(facts: Mapping[str, object]) -> bool | None:
    requested_amount = facts.get("requested_amount")
    owned_house_count = facts.get("owned_house_count")
    if requested_amount is None or owned_house_count is None:
        return None
    if requested_amount < Decimal("5000000"):
        return False
    if owned_house_count >= 1:
        is_regulated_region = bool(facts.get("is_regulated_region"))
        limit = Decimal("200000000") if is_regulated_region else Decimal("300000000")
    else:
        limit = Decimal("500000000")
    return requested_amount <= limit


KB_STAR_JEONSE_LOAN_SGI_PACK = ProductRulePack(
    product_name="KB스타 전세자금대출(SGI_서울보증보험)",
    category=ProductCategory.JEONSE_LOAN,
    version="준법감시인 심의필 제2026-1803-14호",
    effective_start_date=date(2026, 4, 21),
    effective_end_date=date(2027, 12, 31),
    source_url=None,
    rules=(
        ComparisonRule(
            code="SGI_JEONSE_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="만 19세 이상 성년만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="SGI_JEONSE_HOUSEHOLD_HEAD",
            field_name="is_household_head",
            operator=ComparisonOperator.EQ,
            expected=True,
            failure_reason="세대주만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="SGI_JEONSE_OWNED_HOUSE_COUNT",
            field_name="owned_house_count",
            operator=ComparisonOperator.LTE,
            expected=1,
            failure_reason="무주택 또는 1주택자만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="SGI_JEONSE_FINANCIAL_COST_BURDEN_RATIO",
            field_name="financial_cost_burden_ratio",
            operator=ComparisonOperator.LTE,
            expected=Decimal("0.40"),
            failure_reason="금융비용부담율이 40%를 초과합니다.",
        ),
        PredicateRule(
            code="SGI_JEONSE_LOAN_AMOUNT_RANGE",
            predicate=_loan_amount_within_tier,
            failure_reason=(
                "대출금액이 한도(무주택 5억원·1주택 3억원·규제지역 1주택 2억원)를 초과합니다."
            ),
            required_fields=("requested_amount", "owned_house_count"),
        ),
    ),
)
