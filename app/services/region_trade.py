"""설정된 공급자 뒤로 지역 실거래 조회를 감춘다.

`loan_product_catalog.load_configured_loan_candidates`와 같은 형태다 —
키워드 전용 `config`/`engine`을 주입받아 테스트에서 DB 없이 갈아끼운다.
"""

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.repositories import (
    build_region_trade_page,
    fetch_region_name,
    fetch_region_trade_count,
    fetch_region_trade_rows,
)
from app.db.session import DatabaseConfigurationError, get_database_engine
from app.schemas.property_trade import RegionTradePage, TradeSort


class RegionTradesUnavailable(RuntimeError):
    """공급자가 없거나 DB에 닿지 못했다. "데이터 없음"과는 다른 상태다."""


class RegionNotFound(LookupError):
    """형식은 맞지만 `sgg_codes`에 없는 코드."""


def load_region_trades(
    sgg_code: str,
    *,
    sort: TradeSort = TradeSort.AREA_ASC,
    page: int = 1,
    page_size: int = 5,
    config: Settings | None = None,
    engine: Engine | None = None,
) -> RegionTradePage:
    """자치구 실거래 한 페이지를 읽는다.

    JSON 폴백을 두지 않는다 — 실거래는 가짜 값을 보여주면 안 되는 데이터이므로,
    공급자가 없으면 조용히 다른 값을 내는 대신 사용 불가를 알린다.
    """

    resolved = config or get_settings()
    if resolved.region_price_provider != "database":
        raise RegionTradesUnavailable("the region trade provider is not configured")

    try:
        database_engine = engine or get_database_engine()
        with database_engine.connect() as connection:
            sgg_name = fetch_region_name(connection, sgg_code)
            if sgg_name is None:
                raise RegionNotFound(sgg_code)
            total_count = fetch_region_trade_count(connection, sgg_code)
            rows = fetch_region_trade_rows(
                connection,
                sgg_code,
                sort,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        # RegionNotFound는 이 두 예외 어디에도 속하지 않아 그대로 밖으로 나간다.
        # 의도된 것이다 — 없는 구는 연결 실패가 아니며, 404와 503은 구별돼야 한다.
        raise RegionTradesUnavailable(
            "the configured database region-trade provider is unavailable"
        ) from exc

    return build_region_trade_page(
        sgg_code,
        sgg_name,
        sort,
        page=page,
        page_size=page_size,
        total_count=total_count,
        rows=rows,
    )


__all__ = [
    "RegionNotFound",
    "RegionTradesUnavailable",
    "load_region_trades",
]
