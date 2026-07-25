from app.rule_engine.product_packs.models import ProductRulePack
from app.rule_engine.product_packs.packs.hf_bogeumjari_loan import HF_BOGEUMJARI_LOAN_PACK
from app.rule_engine.product_packs.packs.kb_clear_sky_savings import KB_CLEAR_SKY_SAVINGS_PACK
from app.rule_engine.product_packs.packs.kb_credit_loan import KB_CREDIT_LOAN_PACK
from app.rule_engine.product_packs.packs.kb_emergency_cash_loan import (
    KB_EMERGENCY_CASH_LOAN_PACK,
)
from app.rule_engine.product_packs.packs.kb_freestyle_savings import KB_FREESTYLE_SAVINGS_PACK
from app.rule_engine.product_packs.packs.kb_general_installment_savings import (
    KB_GENERAL_INSTALLMENT_SAVINGS_PACK,
)
from app.rule_engine.product_packs.packs.kb_general_term_deposit import (
    KB_GENERAL_TERM_DEPOSIT_PACK,
)
from app.rule_engine.product_packs.packs.kb_golden_life_pension_deposit import (
    KB_GOLDEN_LIFE_PENSION_DEPOSIT_PACK,
)
from app.rule_engine.product_packs.packs.kb_merchant_preferred_savings import (
    KB_MERCHANT_PREFERRED_SAVINGS_PACK,
)
from app.rule_engine.product_packs.packs.kb_mortgage_loan import KB_MORTGAGE_LOAN_PACK
from app.rule_engine.product_packs.packs.kb_mutual_installment_fixed import (
    KB_MUTUAL_INSTALLMENT_FIXED_PACK,
)
from app.rule_engine.product_packs.packs.kb_mutual_installment_free import (
    KB_MUTUAL_INSTALLMENT_FREE_PACK,
)
from app.rule_engine.product_packs.packs.kb_my_own_savings import KB_MY_OWN_SAVINGS_PACK
from app.rule_engine.product_packs.packs.kb_premium_installment_savings import (
    KB_PREMIUM_INSTALLMENT_SAVINGS_PACK,
)
from app.rule_engine.product_packs.packs.kb_salary_credit_loan import KB_SALARY_CREDIT_LOAN_PACK
from app.rule_engine.product_packs.packs.kb_star_apartment_mortgage_loan import (
    KB_STAR_APARTMENT_MORTGAGE_LOAN_PACK,
)
from app.rule_engine.product_packs.packs.kb_star_jeonse_loan_hf import KB_STAR_JEONSE_LOAN_HF_PACK
from app.rule_engine.product_packs.packs.kb_star_jeonse_loan_hug import (
    KB_STAR_JEONSE_LOAN_HUG_PACK,
)
from app.rule_engine.product_packs.packs.kb_star_jeonse_loan_sgi import (
    KB_STAR_JEONSE_LOAN_SGI_PACK,
)
from app.rule_engine.product_packs.packs.kb_star_savings_3 import KB_STAR_SAVINGS_3_PACK
from app.rule_engine.product_packs.packs.kb_star_term_deposit import (
    KB_STAR_TERM_DEPOSIT_PACK,
)
from app.rule_engine.product_packs.packs.kb_super_term_deposit import (
    KB_SUPER_TERM_DEPOSIT_PACK,
)
from app.rule_engine.product_packs.packs.kb_travel_savings import KB_TRAVEL_SAVINGS_PACK

# 검수가 끝난 실제 상품 Pack만 이 파일에서 import하고 아래 tuple에 추가한다.
# `example_product.py`는 복사 전용이므로 PRODUCT_RULE_PACKS에 넣지 않는다.

PRODUCT_RULE_PACKS: tuple[ProductRulePack, ...] = (
    # 예금
    KB_GOLDEN_LIFE_PENSION_DEPOSIT_PACK,
    KB_SUPER_TERM_DEPOSIT_PACK,
    KB_STAR_TERM_DEPOSIT_PACK,
    KB_GENERAL_TERM_DEPOSIT_PACK,
    # 적금
    KB_GENERAL_INSTALLMENT_SAVINGS_PACK,
    KB_PREMIUM_INSTALLMENT_SAVINGS_PACK,
    KB_MUTUAL_INSTALLMENT_FREE_PACK,
    KB_MUTUAL_INSTALLMENT_FIXED_PACK,
    KB_MY_OWN_SAVINGS_PACK,
    KB_FREESTYLE_SAVINGS_PACK,
    KB_MERCHANT_PREFERRED_SAVINGS_PACK,
    KB_TRAVEL_SAVINGS_PACK,
    KB_CLEAR_SKY_SAVINGS_PACK,
    KB_STAR_SAVINGS_3_PACK,
    # 주택담보대출
    KB_MORTGAGE_LOAN_PACK,
    HF_BOGEUMJARI_LOAN_PACK,
    KB_STAR_APARTMENT_MORTGAGE_LOAN_PACK,
    # 전세자금대출
    KB_STAR_JEONSE_LOAN_HUG_PACK,
    KB_STAR_JEONSE_LOAN_HF_PACK,
    KB_STAR_JEONSE_LOAN_SGI_PACK,
    # 개인신용대출
    KB_CREDIT_LOAN_PACK,
    KB_SALARY_CREDIT_LOAN_PACK,
    KB_EMERGENCY_CASH_LOAN_PACK,
)

__all__ = ["PRODUCT_RULE_PACKS"]
