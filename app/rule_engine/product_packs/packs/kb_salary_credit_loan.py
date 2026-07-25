from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 개인신용대출 #2, regulatory_review_no
# "준법감시인 심의필 제2025-5172-69호"). join_member="CSS 대출적격자 중 동일직장
# 1년 이상 재직 ..., 급여이체 대행계약 업체로부터 1회 이상 급여이체 실적 ...
# (개인사업자, 연금이체자 등 제외)". loan_lmt="무보증 최고 1억5천만원 이내
# (종합통장자동대출 최고 1억원 이내)". spcl_cnd(실적연동/내맘대로 우대금리)는
# 우대금리 조건이라 제외.


def _not_excluded_applicant(facts: Mapping[str, object]) -> bool | None:
    is_sole_proprietor = facts.get("is_sole_proprietor")
    is_pension_transfer_recipient = facts.get("is_pension_transfer_recipient")
    if is_sole_proprietor is None or is_pension_transfer_recipient is None:
        return None
    return not is_sole_proprietor and not is_pension_transfer_recipient


def _loan_amount_within_tier(facts: Mapping[str, object]) -> bool | None:
    requested_amount = facts.get("requested_amount")
    if requested_amount is None:
        return None
    limit = Decimal("100000000") if facts.get("is_overdraft_type") else Decimal("150000000")
    return requested_amount <= limit


KB_SALARY_CREDIT_LOAN_PACK = ProductRulePack(
    product_name="KB 급여이체신용대출",
    category=ProductCategory.CREDIT_LOAN,
    version="준법감시인 심의필 제2025-5172-69호",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=date(2027, 11, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_SALARY_CREDIT_MIN_EMPLOYMENT_MONTHS",
            field_name="employment_months",
            operator=ComparisonOperator.GTE,
            expected=12,
            failure_reason="동일직장 1년 이상 재직해야 합니다.",
        ),
        ComparisonRule(
            code="KB_SALARY_CREDIT_MIN_SALARY_TRANSFER_COUNT",
            field_name="salary_transfer_count",
            operator=ComparisonOperator.GTE,
            expected=1,
            failure_reason="당행 급여이체 실적이 1회 이상 있어야 합니다.",
        ),
        PredicateRule(
            code="KB_SALARY_CREDIT_EXCLUDED_APPLICANT",
            predicate=_not_excluded_applicant,
            failure_reason="개인사업자 또는 연금이체자는 신청할 수 없습니다.",
            required_fields=("is_sole_proprietor", "is_pension_transfer_recipient"),
        ),
        PredicateRule(
            code="KB_SALARY_CREDIT_AMOUNT_LIMIT",
            predicate=_loan_amount_within_tier,
            failure_reason="대출금액이 한도(종합통장자동대출 1억원·그 외 1.5억원)를 초과합니다.",
            required_fields=("requested_amount",),
        ),
    ),
)
