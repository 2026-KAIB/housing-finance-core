from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

# 원문(`예금 리스트 4개.txt` #4, verified_at 2026-07-23, source_type=manual_pdf,
# regulatory_review_no="준법감시인 심의필 제2026-3320-2호", effective_period 명시값 사용).
# join_member와 spcl_cnd가 null이므로 가입대상·우대조건을 임의로 만들지 않는다.
# 가입기간별 금리는 optionList, 추가입금·분할해지 불가는 상품 이용 조건, 만기후 및
# 36개월 초과 금리는 후속 이자 계산 조건이므로 이 Pack에서 제외하고 예적금 엔진에 전달한다.
# 현재 원문에서 확정할 수 있는 가입 필수조건은 최저 가입금액뿐이다.

KB_GENERAL_TERM_DEPOSIT_PACK = ProductRulePack(
    product_name="일반정기예금",
    category=ProductCategory.TERM_DEPOSIT,
    version="준법감시인 심의필 제2026-3320-2호",
    effective_start_date=date(2026, 7, 21),
    effective_end_date=date(2028, 6, 30),
    source_url=None,
    rules=(
        ComparisonRule(
            code="KB_GENERAL_TD_MIN_DEPOSIT_AMOUNT",
            field_name="deposit_amount",
            operator=ComparisonOperator.GTE,
            expected=100_000,
            failure_reason="가입금액은 10만원 이상이어야 합니다.",
        ),
    ),
)
