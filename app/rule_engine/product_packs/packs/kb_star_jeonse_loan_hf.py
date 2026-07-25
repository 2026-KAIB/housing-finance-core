from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 전세자금대출 #2, regulatory_review_no
# "준법감시인 심의필 제2026-2770-1호"). join_member="... 세대주 (임차보증금 수도권
# 7억원, 그 외 5억원 이하, 5% 이상 지급, 무주택 또는 1주택)" — HUG 전세자금대출과
# 임차보증금·주택보유 조건이 동일하다. "5% 이상 지급"은 이번 1차 판정에서 제외.
# loan_lmt="최소 5백만원 이상 최대 2억 2천 2백만원 이내 (신혼부부 또는 다둥이가구는
# 최대 2억원 이내)" — 일반 상한이 신혼/다둥이가구에서 오히려 낮아지는 구조를
# 그대로 반영한다. spcl_cnd(신혼/다둥이 협약·전자계약·취약차주 우대금리)는
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
    if requested_amount is None:
        return None
    if requested_amount < Decimal("5000000"):
        return False
    is_newlywed_or_multi_child = bool(facts.get("is_newlywed_or_multi_child"))
    limit = Decimal("200000000") if is_newlywed_or_multi_child else Decimal("222000000")
    return requested_amount <= limit


KB_STAR_JEONSE_LOAN_HF_PACK = ProductRulePack(
    product_name="KB스타 전세자금대출(HF_한국주택금융공사)",
    category=ProductCategory.JEONSE_LOAN,
    version="준법감시인 심의필 제2026-2770-1호",
    effective_start_date=date(2026, 6, 22),
    effective_end_date=date(2028, 5, 31),
    source_url=None,
    rules=(
        ComparisonRule(
            code="HF_JEONSE_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="민법상 성년(만 19세 이상)만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="HF_JEONSE_HOUSEHOLD_HEAD",
            field_name="is_household_head",
            operator=ComparisonOperator.EQ,
            expected=True,
            failure_reason="세대주만 신청할 수 있습니다.",
        ),
        ComparisonRule(
            code="HF_JEONSE_OWNED_HOUSE_COUNT",
            field_name="owned_house_count",
            operator=ComparisonOperator.LTE,
            expected=1,
            failure_reason="무주택 또는 1주택자만 신청할 수 있습니다.",
        ),
        PredicateRule(
            code="HF_JEONSE_DEPOSIT_CAP",
            predicate=_lease_deposit_within_region_cap,
            failure_reason="임차보증금이 지역별 한도(수도권 7억원, 그 외 5억원)를 초과합니다.",
            required_fields=("lease_deposit", "is_capital_region"),
        ),
        PredicateRule(
            code="HF_JEONSE_LOAN_AMOUNT_RANGE",
            predicate=_loan_amount_within_tier,
            failure_reason=(
                "대출금액은 5백만원 이상, 신혼·다둥이 2억원·그 외 2억2천2백만원 이내여야 합니다."
            ),
            required_fields=("requested_amount",),
        ),
    ),
)
