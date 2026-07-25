from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 원문(selected_23_products.json 적금 #7, regulatory_review_no
# "준법감시인 심의필 제2024-5171-11호"). join_member="만 14세 이상의 실명의
# 개인(개인사업자 포함), 법인, 임의단체 (1인/업체당 최대 5계좌)" 중 계좌 수 제약은
# 판정 불가라 제외 — 연령만 판정(가입 주체 유형은 사실상 제한 없음).
# etc_note 가입금액이 "초회/2회차 이후"로 다르므로 is_first_payment로 분기한다.
# spcl_cnd(가맹점결제계좌/KB국민카드/사업성공 우대이율)는 우대금리 조건이라 제외.


def _min_monthly_payment_by_installment(facts: Mapping[str, object]) -> bool | None:
    is_first_payment = facts.get("is_first_payment")
    amount = facts.get("monthly_payment_amount")
    if is_first_payment is None or amount is None:
        return None
    minimum = 10_000 if is_first_payment else 1_000
    return amount >= minimum


KB_MERCHANT_PREFERRED_SAVINGS_PACK = ProductRulePack(
    product_name="KB가맹점우대적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2024-5171-11호",
    effective_start_date=date(2024, 11, 13),
    effective_end_date=date(2026, 9, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_MERCHANT_SAVINGS_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=14,
            failure_reason="만 14세 이상만 가입할 수 있습니다.",
        ),
        PredicateRule(
            code="KB_MERCHANT_SAVINGS_MIN_MONTHLY_PAYMENT",
            predicate=_min_monthly_payment_by_installment,
            failure_reason="초회 1만원 이상, 2회차 이후 1천원 이상 납입해야 합니다.",
            required_fields=("is_first_payment", "monthly_payment_amount"),
        ),
        ComparisonRule(
            code="KB_MERCHANT_SAVINGS_MAX_MONTHLY_PAYMENT",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.LTE,
            expected=10_000_000,
            failure_reason="월 저축금은 1천만원 이내여야 합니다.",
        ),
    ),
)
