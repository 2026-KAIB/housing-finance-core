from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

# 원문(selected_23_products.json 적금 #3, regulatory_review_no
# "준법감시인 심의필 제2024-5171-21호"). join_member="제한없음 (개인, 법인, 단체)"라
# 회원조건 없음. spcl_cnd(자동이체/통장보유 우대이율)는 우대금리 조건이라 제외.

KB_MUTUAL_INSTALLMENT_FREE_PACK = ProductRulePack(
    product_name="KB상호부금(자유적립식)",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="준법감시인 심의필 제2024-5171-21호",
    effective_start_date=date(2024, 11, 13),
    effective_end_date=date(2026, 9, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_MUTUAL_FREE_MONTHLY_PAYMENT_RANGE",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(10_000, 5_000_000),
            failure_reason="회차별 저축금은 1만원 이상 월 5백만원 이내여야 합니다.",
        ),
    ),
)
