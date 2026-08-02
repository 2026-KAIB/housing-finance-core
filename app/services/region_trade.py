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


# 조회 경로를 태우기 위한 코드일 뿐이다. 이 구에 거래가 없어도(빈 결과) 준비
# 확인은 통과한다 — 데이터 없음과 조회 불가는 다른 상태다.
_PROBE_SGG_CODE = "11680"


def probe_region_trades(
    *,
    config: Settings | None = None,
    engine: Engine | None = None,
) -> None:
    """설정된 실거래 공급원이 **실제로 조회되는지**만 확인한다.

    준비 확인용이라 페이지를 만들지 않고 한 행만 읽는다. `SELECT 1`로 대신하지
    않는 이유는, 접속은 되지만 `apt_trades`·`sgg_codes` 권한이 없는 배포가
    이 저장소에서 실제로 겪은 형태이기 때문이다 — 연결만 확인하면 그 배포가
    '준비됨'으로 통과한다.
    """

    resolved = config or get_settings()
    if resolved.region_price_provider != "database":
        raise RegionTradesUnavailable("the region trade provider is not configured")

    try:
        database_engine = engine or get_database_engine()
        with database_engine.connect() as connection:
            fetch_region_name(connection, _PROBE_SGG_CODE)
            fetch_region_trade_rows(
                connection,
                _PROBE_SGG_CODE,
                TradeSort.AREA_ASC,
                limit=1,
                offset=0,
            )
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise RegionTradesUnavailable(
            "the configured database region-trade provider is unavailable"
        ) from exc


__all__ = [
    "RegionNotFound",
    "RegionTradesUnavailable",
    "load_region_trades",
    "probe_region_trades",
]
