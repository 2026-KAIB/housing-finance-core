from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

# 원문(selected_23_products.json 적금 #4, regulatory_review_no
# "준법감시인 심의필 제2024-5171-22호"). join_member="제한없음 (개인, 법인, 단체)"라
# 회원조건 없음. etc_note에 상한 명시가 없어 최저금액만 판정한다.
# spcl_cnd(자동이체/통장보유 우대이율)는 우대금리 조건이라 제외.

KB_MUTUAL_INSTALLMENT_FIXED_PACK = ProductRulePack(
    product_name="KB상호부금(정액적립식)",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2024-5171-22호",
    effective_start_date=date(2024, 11, 13),
    effective_end_date=date(2026, 9, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_MUTUAL_FIXED_MIN_MONTHLY_PAYMENT",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.GTE,
            expected=10_000,
            failure_reason="월저축금은 1만원 이상이어야 합니다.",
        ),
    ),
)
