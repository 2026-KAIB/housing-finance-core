from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(Notion "예금" #3, verified_at 2026-07-23, source_type=api, dcls_strt_day=20260722):
# spcl_cnd="해당무" → 우대조건 없음. join_deny="1"(제한없음)이라 회원 조건은 join_member
# 자유텍스트("실명의 개인 또는 개인사업자")로만 인코딩한다. mtrt_int(만기후 이율)는
# 가입조건이 아니므로 이 Pack에 포함하지 않는다(README: 우대금리·이자 조건과 가입조건을 섞지 않음).
# 근거 URL은 원본 데이터에 없어 비워둔다.


def _is_individual_or_sole_proprietor(facts: Mapping[str, object]) -> bool | None:
    applicant_type = facts.get("applicant_type")
    if applicant_type is None:
        return None
    return applicant_type in ("individual", "sole_proprietor")


KB_STAR_TERM_DEPOSIT_PACK = ProductRulePack(
    product_name="KB Star 정기예금",
    category=ProductCategory.TERM_DEPOSIT,
    version="api-20260722",
    effective_start_date=date(2026, 7, 22),
    effective_end_date=None,
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_STAR_TD_MIN_DEPOSIT_AMOUNT",
            field_name="deposit_amount",
            operator=ComparisonOperator.GTE,
            expected=1_000_000,
            failure_reason="가입금액은 1백만원 이상이어야 합니다.",
        ),
        PredicateRule(
            code="KB_STAR_TD_MEMBER_ELIGIBILITY",
            predicate=_is_individual_or_sole_proprietor,
            failure_reason="실명의 개인 또는 개인사업자만 가입할 수 있습니다.",
            required_fields=("applicant_type",),
        ),
    ),
)
