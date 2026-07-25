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
    # 기본 한도(7천만원) 이내면 가구 유형과 무관하게 통과, 최고 한도(1억원) 초과면
    # 무조건 탈락이다. 그 사이는 자녀 수·신혼 여부를 알아야 판정할 수 있으므로
    # 결측 시 UNKNOWN을 반환한다(추측 금지). 다자녀>1자녀>신혼 순으로 유리한
    # 등급을 우선 적용한다.
    income = facts.get("combined_annual_income")
    if income is None:
        return None
    if income <= Decimal("70000000"):
        return True
    if income > Decimal("100000000"):
        return False

    child_count = facts.get("child_count")
    if child_count is None:
        return None
    if child_count >= 2:
        return True
    if child_count == 1:
        return income <= Decimal("90000000")

    is_newlywed = facts.get("is_newlywed")
    if is_newlywed is None:
        return None
    limit = Decimal("85000000") if is_newlywed else Decimal("70000000")
    return income <= limit


def _loan_amount_within_tier(facts: Mapping[str, object]) -> bool | None:
    # 기본 한도(3.6억원) 이내면 신청자 유형과 무관하게 통과, 최고 한도(4.2억원)
    # 초과면 무조건 탈락이다. 그 사이는 생애최초·다자녀/전세사기피해자 여부를
    # 알아야 판정할 수 있으므로 결측 시 UNKNOWN을 반환한다(추측 금지).
    requested_amount = facts.get("requested_amount")
    if requested_amount is None:
        return None
    if requested_amount <= Decimal("360000000"):
        return True
    if requested_amount > Decimal("420000000"):
        return False

    is_first_home_buyer = facts.get("is_first_home_buyer")
    if requested_amount <= Decimal("400000000"):
        if is_first_home_buyer:
            return True
        is_multi_child_or_victim = facts.get("is_multi_child_or_jeonse_fraud_victim")
        if is_multi_child_or_victim:
            return True
        if is_first_home_buyer is None or is_multi_child_or_victim is None:
            return None
        return False

    # 400M < requested_amount <= 420M: 생애최초 주택구입자만 해당
    if is_first_home_buyer is None:
        return None
    return bool(is_first_home_buyer)


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
