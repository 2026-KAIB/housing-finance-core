import unicodedata
from datetime import date

from app.rule_engine.product_packs.models import ProductRulePack
from app.rule_engine.product_packs.packs import PRODUCT_RULE_PACKS

# 상품 이름은 DB ID 대신 현재 단계의 안전한 조회 키로 사용한다.
# 완전일치가 원칙이며 유니코드, 영문 대소문자, 연속 공백만 정규화한다.
# 상품명이 바뀌거나 표기가 여러 개면 Pack의 aliases에 정확한 별칭을 추가한다.
# 같은 이름의 개정 Pack은 적용기간이 겹치지 않게 등록하고 기준일로 선택한다.


class ProductRulePackNotFoundError(LookupError):
    pass


class ProductRulePackAmbiguousError(LookupError):
    pass


class ProductRulePackRegistry:
    def __init__(self, packs: tuple[ProductRulePack, ...] = ()) -> None:
        self._packs: list[ProductRulePack] = []
        for pack in packs:
            self.register(pack)

    def register(self, pack: ProductRulePack) -> None:
        new_names = _normalized_names(pack)
        for existing in self._packs:
            if new_names.isdisjoint(_normalized_names(existing)):
                continue
            if _periods_overlap(existing, pack):
                raise ValueError(
                    "같은 상품명 또는 별칭에 적용기간이 겹치는 Pack을 등록할 수 없습니다: "
                    f"{existing.source_version}, {pack.source_version}"
                )
        self._packs.append(pack)

    def resolve(self, product_name: str, as_of: date) -> ProductRulePack:
        normalized = normalize_product_name(product_name)
        candidates = [
            pack for pack in self._packs if normalized in _normalized_names(pack)
        ]
        active = [pack for pack in candidates if pack.is_active_on(as_of)]

        if not active:
            if candidates:
                raise ProductRulePackNotFoundError(
                    f"'{product_name}' 상품은 {as_of.isoformat()} 기준으로 유효한 Pack이 없습니다."
                )
            raise ProductRulePackNotFoundError(
                f"'{product_name}' 이름으로 등록된 상품 Rule Pack이 없습니다."
            )
        if len(active) > 1:
            versions = ", ".join(pack.source_version for pack in active)
            raise ProductRulePackAmbiguousError(
                f"'{product_name}'에 적용할 Pack이 여러 개입니다: {versions}"
            )
        return active[0]

    @property
    def product_names(self) -> tuple[str, ...]:
        return tuple(pack.product_name for pack in self._packs)


def normalize_product_name(product_name: str) -> str:
    normalized = unicodedata.normalize("NFKC", product_name)
    return " ".join(normalized.split()).casefold()


def _normalized_names(pack: ProductRulePack) -> set[str]:
    return {
        normalize_product_name(name)
        for name in (pack.product_name, *pack.aliases)
    }


def _periods_overlap(first: ProductRulePack, second: ProductRulePack) -> bool:
    first_end = first.effective_end_date or date.max
    second_end = second.effective_end_date or date.max
    return first.effective_start_date <= second_end and second.effective_start_date <= first_end


DEFAULT_PRODUCT_RULE_PACK_REGISTRY = ProductRulePackRegistry(PRODUCT_RULE_PACKS)
