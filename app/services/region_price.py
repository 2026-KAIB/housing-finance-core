"""설정된 시세 공급자를 하나의 계약 뒤로 감춘다.

`loan_product_catalog.load_configured_loan_candidates`와 같은 형태다 —
키워드 전용 `config`/`engine`을 주입받아 테스트에서 DB 없이 갈아끼운다.
"""

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.repositories import (
    build_region_price_reference,
    fetch_region_name,
    fetch_region_price_rows,
)
from app.db.session import DatabaseConfigurationError, get_database_engine
from app.schemas.property_price import RegionPriceReference


class RegionPriceUnavailable(RuntimeError):
    """공급자가 없거나 DB에 닿지 못했다. "데이터 없음"과는 다른 상태다."""


class RegionNotFound(LookupError):
    """형식은 맞지만 `sgg_codes`에 없는 코드."""


def load_region_price_reference(
    sgg_code: str,
    *,
    config: Settings | None = None,
    engine: Engine | None = None,
) -> RegionPriceReference:
    """자치구 시세를 읽는다.

    JSON 폴백을 두지 않는다 — 시세는 가짜 값을 보여주면 안 되는 데이터이므로,
    공급자가 없으면 조용히 다른 값을 내는 대신 사용 불가를 알린다.
    """

    resolved = config or get_settings()
    if resolved.region_price_provider != "database":
        raise RegionPriceUnavailable("the region price provider is not configured")

    try:
        database_engine = engine or get_database_engine()
        with database_engine.connect() as connection:
            sgg_name = fetch_region_name(connection, sgg_code)
            if sgg_name is None:
                raise RegionNotFound(sgg_code)
            rows = fetch_region_price_rows(connection, sgg_code)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        # RegionNotFound는 이 두 예외 어디에도 속하지 않아 그대로 밖으로 나간다.
        # 의도된 것이다 — 없는 구는 연결 실패가 아니며, 404와 503은 구별돼야 한다.
        raise RegionPriceUnavailable(
            "the configured database region-price provider is unavailable"
        ) from exc

    return build_region_price_reference(sgg_code, sgg_name, rows)


__all__ = [
    "RegionNotFound",
    "RegionPriceUnavailable",
    "load_region_price_reference",
]
