from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import PredicateRule

# 원문(selected_23_products.json 적금 #6, source_type=api, dcls_strt_day=20260720).
# join_member="실명의 개인 또는 개인사업자". etc_note에 가입금액 명시가 없어(채널
# 안내뿐) 금액 조건은 만들지 않는다. spcl_cnd(9가지 항목 중 6가지 선택 우대이율)는
# 우대금리 조건이라 제외.


def _is_individual_or_sole_proprietor(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type in ("individual", "sole_proprietor")


KB_FREESTYLE_SAVINGS_PACK = ProductRulePack(
    product_name="KB내맘대로적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="api-20260720",
    effective_start_date=date(2026, 7, 20),
    effective_end_date=None,
    source_url=None,
    rules=(
        PredicateRule(
            code="KB_FREESTYLE_SAVINGS_MEMBER_ELIGIBILITY",
            predicate=_is_individual_or_sole_proprietor,
            failure_reason="실명의 개인 또는 개인사업자만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
    ),
)
