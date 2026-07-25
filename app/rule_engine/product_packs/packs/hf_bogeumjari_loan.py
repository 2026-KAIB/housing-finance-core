from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import PredicateRule

# 원문(selected_23_products.json 주택담보대출 #2, regulatory_review_no
# "준법감시인 심의필 제2025-4397-1호"). join_member="민법상 성년 무주택자(부부합산
# 연소득 7천만원 이하, 신혼 8천5백만원, 1자녀 9천만원, 다자녀 1억원 이하 등)".
# loan_lmt="3.6억원 이내 (다자녀가구/전세사기피해자 4억원, 생애최초 4.2억원 이내)".
# etc_note의 대출기간별 연령제한(40년/50년)은 상품구조 세부사항이 많아 이번
# 1차 판정에서는 제외한다(추후 보강). spcl_cnd(사회적배려층 등 우대금리)는
# 우대금리 조건이라 제외.


def _is_adult_homeless(facts: Mapping[str, object]) -> bool | None:
    age = facts.get("age")
    owns_house = facts.get("owns_house")
    if age is None or owns_house is None:
        return None
    return age >= 19 and owns_house is False


def _income_within_household_tier(facts: Mapping[str, object]) -> bool | None:
    income = facts.get("combined_annual_income")
    if income is None:
        return None
    child_count = facts.get("child_count") or 0
    is_newlywed = bool(facts.get("is_newlywed"))
    if child_count >= 2:
        limit = Decimal("100000000")
    elif child_count == 1:
        limit = Decimal("90000000")
    elif is_newlywed:
        limit = Decimal("85000000")
    else:
        limit = Decimal("70000000")
    return income <= limit


def _loan_amount_within_tier(facts: Mapping[str, object]) -> bool | None:
    requested_amount = facts.get("requested_amount")
    if requested_amount is None:
        return None
    if facts.get("is_first_home_buyer"):
        limit = Decimal("420000000")
    elif facts.get("is_multi_child_or_jeonse_fraud_victim"):
        limit = Decimal("400000000")
    else:
        limit = Decimal("360000000")
    return requested_amount <= limit


HF_BOGEUMJARI_LOAN_PACK = ProductRulePack(
    product_name="한국주택금융공사 아낌e-보금자리론",
    category=ProductCategory.MORTGAGE_LOAN,
    version="준법감시인 심의필 제2025-4397-1호",
    effective_start_date=date(2025, 11, 20),
    effective_end_date=date(2027, 10, 31),
    source_url=None,
    rules=(
        PredicateRule(
            code="BOGEUMJARI_ADULT_HOMELESS",
            predicate=_is_adult_homeless,
            failure_reason="민법상 성년 무주택자만 신청할 수 있습니다.",
            required_fields=("age", "owns_house"),
        ),
        PredicateRule(
            code="BOGEUMJARI_INCOME_LIMIT",
            predicate=_income_within_household_tier,
            failure_reason="부부합산 연소득이 가구 유형별 한도를 초과합니다.",
            required_fields=("combined_annual_income",),
        ),
        PredicateRule(
            code="BOGEUMJARI_LOAN_AMOUNT_LIMIT",
            predicate=_loan_amount_within_tier,
            failure_reason="요청 대출액이 신청자 유형별 한도를 초과합니다.",
            required_fields=("requested_amount",),
        ),
    ),
)
