from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 전세자금대출 #1, regulatory_review_no
# "준법감시인 심의필 제2026-1803-13호"). join_member="만 19세 이상 ... 세대주 ...
# (임차보증금 수도권 7억원, 그 외 5억원 이내, 5% 이상 지급, 무주택 또는 1주택)".
# "5% 이상 지급" 조건은 이번 1차 판정에서는 제외한다(계약금 지급 시점 관련
# 데이터 정합성 확인 필요). loan_lmt="최소 5백만원 이상 최대 4억원(1주택자 2억원)
# 이내 (임차보증금의 80% 이내 등)" 중 임차보증금 80% 조건은 별도 필드가 필요해
# 이번 1차 판정에서는 정액 한도만 판정한다. spcl_cnd(전자계약/취약차주 우대금리)는
# 우대금리 조건이라 제외.


def _lease_deposit_within_region_cap(facts: Mapping[str, object]) -> bool | None:
    lease_deposit = facts.get("lease_deposit")
    is_capital_region = facts.get("is_capital_region")
    if lease_deposit is None or is_capital_region is None:
        return None
    cap = Decimal("700000000") if is_capital_region else Decimal("500000000")
    return lease_deposit <= cap


def _loan_amount_within_tier(facts: Mapping[str, object]) -> bool | None:
    requested_amount = facts.get("requested_amount")
    owned_house_count = facts.get("owned_house_count")
    if requested_amount is None or owned_house_count is None:
        return None
    if requested_amount < Decimal("5000000"):
        return False
    limit = Decimal("200000000") if owned_house_count >= 1 else Decimal("400000000")
    return requested_amount <= limit


KB_STAR_JEONSE_LOAN_HUG_PACK = ProductRulePack(
    product_name="KB스타 전세자금대출(HUG_주택도시보증공사)",
    category=ProductCategory.JEONSE_LOAN,
    version="준법감시인 심의필 제2026-1803-13호",
    effective_start_date=date(2026, 4, 21),
    effective_end_date=date(2027, 12, 31),
    source_url=None,
    rules=(
        ComparisonRule(
            code="HUG_JEONSE_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="만 19세 이상만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="HUG_JEONSE_HOUSEHOLD_HEAD",
            field_name="is_household_head",
            operator=ComparisonOperator.EQ,
            expected=True,
            failure_reason="세대주(단독세대주 포함)만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="HUG_JEONSE_OWNED_HOUSE_COUNT",
            field_name="owned_house_count",
            operator=ComparisonOperator.LTE,
            expected=1,
            failure_reason="무주택 또는 1주택자만 신청할 수 있습니다.",
        ),
        PredicateRule(
            code="HUG_JEONSE_DEPOSIT_CAP",
            predicate=_lease_deposit_within_region_cap,
            failure_reason="임차보증금이 지역별 한도(수도권 7억원, 그 외 5억원)를 초과합니다.",
            required_fields=("lease_deposit", "is_capital_region"),
        ),
        PredicateRule(
            code="HUG_JEONSE_LOAN_AMOUNT_RANGE",
            predicate=_loan_amount_within_tier,
            failure_reason="대출금액은 5백만원 이상, 무주택 4억원·1주택 2억원 이내여야 합니다.",
            required_fields=("requested_amount", "owned_house_count"),
        ),
    ),
)
