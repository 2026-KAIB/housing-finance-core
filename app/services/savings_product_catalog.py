"""설정된 예·적금 상품 공급원을 엔진 계약 하나 뒤로 감춘다.

대출 쪽(`loan_product_catalog.py`)과 같은 모양이지만 **JSON 스냅샷 갈래가 없다.**
예·적금 스냅샷을 아직 뜬 적이 없어서다. 없는 파일을 가리키는 설정을 만들어 두고
조회 실패를 빈 목록으로 바꾸면 "가입 가능한 상품이 없음"으로 읽힌다 — 그건
`SAVINGS_PRODUCT_PROVIDER=json`이 실제로 동작하는 것처럼 보이게 만드는 거짓말이다.
스냅샷이 생기면 이 자리에 대출과 같은 갈래를 더한다.
"""

from datetime import date

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.repositories.savings_product_repository import (
    fetch_savings_product_candidates,
)
from app.db.session import DatabaseConfigurationError, get_database_engine
from app.rule_engine.product_packs.handoff import ProductCandidate


class SavingsProductCatalogUnavailable(RuntimeError):
    """선택된 공급원이 믿을 수 있는 후보를 내지 못했다."""


def load_configured_savings_candidates(
    *,
    as_of: date,
    config: Settings | None = None,
    engine: Engine | None = None,
) -> tuple[ProductCandidate, ...]:
    """설정된 공급원에서 예·적금 후보를 읽는다."""

    resolved = config or get_settings()
    if resolved.savings_product_provider != "database":
        raise SavingsProductCatalogUnavailable(
            "the configured savings-product provider is not available: "
            f"{resolved.savings_product_provider}"
        )
    try:
        database_engine = engine or get_database_engine()
        with database_engine.connect() as connection:
            return fetch_savings_product_candidates(connection, as_of=as_of)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise SavingsProductCatalogUnavailable(
            "the configured database savings-product provider is unavailable"
        ) from exc


__all__ = [
    "SavingsProductCatalogUnavailable",
    "load_configured_savings_candidates",
]
