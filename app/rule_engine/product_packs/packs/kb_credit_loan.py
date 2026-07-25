from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import PredicateRule

# 원문(selected_23_products.json 개인신용대출 #1, regulatory_review_no
# "준법감시인 심의필 제 2025-5172-66"). join_member="CSS 대출적격자로 각 직군별
# 재직기간 기준을 충족하고 ..."는 직군별 세부 기준표가 원문에 없어 판정 불가라
# 제외한다(추측 금지). loan_lmt="최대 3.5억원 이내 (재직기간 1년미만 시 최대
# 1억원, 종합통장자동대출은 최대 1.5억원)"만 판정 가능하다. spcl_cnd(실적연동/
# 영업점장 우대금리)는 우대금리 조건이라 제외.


def _loan_amount_within_tier(facts: Mapping[str, object]) -> bool | None:
    requested_amount = facts.get("requested_amount")
    if requested_amount is None:
        return None
    if facts.get("is_overdraft_type"):
        limit = Decimal("150000000")
    else:
        employment_months = facts.get("employment_months")
        if employment_months is None:
            return None
        limit = Decimal("100000000") if employment_months < 12 else Decimal("350000000")
    return requested_amount <= limit


KB_CREDIT_LOAN_PACK = ProductRulePack(
    product_name="KB 신용대출",
    category=ProductCategory.CREDIT_LOAN,
    version="준법감시인 심의필 제 2025-5172-66",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=date(2027, 11, 30),
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_CREDIT_LOAN_AMOUNT_LIMIT",
            predicate=_loan_amount_within_tier,
            failure_reason=(
                "대출금액이 한도(재직 1년미만 1억원·종합통장자동대출 1.5억원·"
                "그 외 3.5억원)를 초과합니다."
            ),
            required_fields=("requested_amount",),
        ),
    ),
)
