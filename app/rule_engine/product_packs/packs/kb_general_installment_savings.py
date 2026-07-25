from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

# 원문(selected_23_products.json 적금 #1, source_type=manual_pdf,
# regulatory_review_no="준법감시인 심의필 제2024-5992-12호").
# join_member="제한없음"이라 회원조건 없음. spcl_cnd(자동이체 우대이율)는
# 우대금리 조건이라 제외. 만기후 이율도 가입조건이 아니므로 제외.

KB_GENERAL_INSTALLMENT_SAVINGS_PACK = ProductRulePack(
    product_name="일반정기적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2024-5992-12호",
    effective_start_date=date(2024, 12, 30),
    effective_end_date=date(2026, 10, 31),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_GENERAL_SAVINGS_MIN_MONTHLY_PAYMENT",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.GTE,
            expected=10_000,
            failure_reason="월 저축금은 1만원 이상이어야 합니다.",
        ),
    ),
)
