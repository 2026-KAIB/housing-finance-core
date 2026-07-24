from app.rule_engine.product_packs.models import ProductRulePack

# 검수가 끝난 실제 상품 Pack만 이 파일에서 import하고 아래 tuple에 추가한다.
# `example_product.py`는 복사 전용이므로 PRODUCT_RULE_PACKS에 넣지 않는다.
# 예: from .kb_star_term_deposit import KB_STAR_TERM_DEPOSIT_PACK
# 예: PRODUCT_RULE_PACKS = (KB_STAR_TERM_DEPOSIT_PACK,)

PRODUCT_RULE_PACKS: tuple[ProductRulePack, ...] = ()

__all__ = ["PRODUCT_RULE_PACKS"]
