from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

# 원문(Notion "예금" #2, verified_at 2026-07-23, source_type=manual_pdf,
# regulatory_review_no="준법감시인 심의필 제2026-3320-1호", effective_period 명시값 사용).
# spcl_cnd(금리우대쿠폰, 비과세가계저축 만기계좌 우대)는 우대금리 조건이라 이 Pack에서
# 제외한다(README: 우대금리 조건과 가입 가능 조건을 섞지 않음). join_member가 null이라
# 회원자격을 특정할 원문 근거가 없으므로 별도 조건을 만들지 않는다(원문 의미 추측 금지).

KB_SUPER_TERM_DEPOSIT_PACK = ProductRulePack(
    product_name="국민수퍼정기예금",
    category=ProductCategory.TERM_DEPOSIT,
    version="준법감시인 심의필 제2026-3320-1호",
    effective_start_date=date(2026, 7, 21),
    effective_end_date=date(2028, 6, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_SUPER_TD_MIN_DEPOSIT_AMOUNT",
            field_name="deposit_amount",
            operator=ComparisonOperator.GTE,
            expected=1_000_000,
            failure_reason="가입금액은 1백만원 이상이어야 합니다.",
        ),
    ),
)
