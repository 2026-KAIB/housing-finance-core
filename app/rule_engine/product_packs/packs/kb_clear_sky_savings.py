from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import PredicateRule

# 원문(selected_23_products.json 적금 #9, source_type=api, dcls_strt_day=20260720).
# join_member="실명의 개인". etc_note "공동명의 불가 (1인 최대 3계좌)"는 판정 불가라
# 제외. etc_note에 가입금액 명시가 없어 금액 조건은 만들지 않는다. spcl_cnd(미션별
# 우대이율)는 우대금리 조건이라 제외.


def _is_individual(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type == "individual"


KB_CLEAR_SKY_SAVINGS_PACK = ProductRulePack(
    product_name="KB맑은하늘적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="api-20260720",
    effective_start_date=date(2026, 7, 20),
    effective_end_date=None,
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_CLEAR_SKY_SAVINGS_MEMBER_ELIGIBILITY",
            predicate=_is_individual,
            failure_reason="실명의 개인만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
    ),
)
