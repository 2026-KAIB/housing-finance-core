"""`v_valid_trades`에서 자치구 실거래를 정렬·페이징해 읽는다(읽기 전용).

`apt_trades`가 아니라 뷰를 읽는 것이 규약이다(db_schema_realestate.md §7).
해제 거래 3,037건 중 2,355건이 정상 거래와 쌍으로 존재하므로, 뷰를 우회하면
같은 거래가 두 번 보이고 해제된 신고가가 최고가로 표시된다.
"""

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.schemas.property_trade import RegionTrade, RegionTradePage, TradeSort

_REGION_NAME_SQL = text("""
    SELECT sgg_nm
      FROM sgg_codes
     WHERE sgg_cd = :sgg_code
""")

_TRADE_COUNT_SQL = text("""
    SELECT count(*)
      FROM v_valid_trades
     WHERE sgg_cd = :sgg_code
""")

# 정렬 조각은 이 표에서만 나온다. 사용자 입력을 ORDER BY에 잇지 않는다.
#
# 모든 조각이 `id ASC`로 끝나는 것이 핵심이다. 면적과 가격은 동점이 흔한데,
# 동점 처리가 비결정적이면 PostgreSQL이 페이지마다 다른 순서를 줄 수 있고,
# 그러면 어떤 거래는 두 페이지에 나오고 어떤 거래는 어느 페이지에도 안 나온다.
_ORDER_BY: dict[TradeSort, str] = {
    TradeSort.AREA_ASC: "exclu_use_ar ASC, id ASC",
    TradeSort.AREA_DESC: "exclu_use_ar DESC, id ASC",
    TradeSort.PRICE_ASC: "deal_amount_won ASC, id ASC",
    TradeSort.PRICE_DESC: "deal_amount_won DESC, id ASC",
}


def order_by_clause(sort: TradeSort) -> str:
    """열거형에 없는 값이면 KeyError를 낸다 — 임의 문자열이 SQL로 새지 않는다."""
    return _ORDER_BY[sort]


def build_region_trade_page(
    sgg_code: str,
    sgg_name: str,
    sort: TradeSort,
    *,
    page: int,
    page_size: int,
    total_count: int,
    rows: Sequence[Mapping[str, Any]],
) -> RegionTradePage:
    """조회 행을 계약으로 바꾼다(순수 함수). DB 없이 매핑을 검증하기 위해 분리했다."""
    return RegionTradePage(
        sgg_code=sgg_code,
        sgg_name=sgg_name,
        sort=sort,
        page=page,
        page_size=page_size,
        total_count=total_count,
        total_pages=max(1, ceil(total_count / page_size)),
        trades=tuple(
            RegionTrade(
                trade_id=row["id"],
                apt_name=row["apt_nm"],
                umd_name=row["umd_nm"],
                road_name=row["road_nm"],
                build_year=row["build_year"],
                exclusive_area_m2=row["exclu_use_ar"],
                floor=row["floor"],
                contract_date=row["contract_date"],
                deal_amount_won=row["deal_amount_won"],
            )
            for row in rows
        ),
    )


def fetch_region_name(connection: Connection, sgg_code: str) -> str | None:
    """`sgg_codes`에 있으면 구 이름을, 없으면 None을 돌려준다."""
    return connection.execute(_REGION_NAME_SQL, {"sgg_code": sgg_code}).scalar_one_or_none()


def fetch_region_trade_count(connection: Connection, sgg_code: str) -> int:
    return connection.execute(_TRADE_COUNT_SQL, {"sgg_code": sgg_code}).scalar_one()


def fetch_region_trade_rows(
    connection: Connection,
    sgg_code: str,
    sort: TradeSort,
    *,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """한 페이지분 거래를 읽는다."""
    statement = text(f"""
        SELECT id,
               apt_nm,
               umd_nm,
               road_nm,
               build_year,
               exclu_use_ar,
               floor,
               contract_date,
               deal_amount_won
          FROM v_valid_trades
         WHERE sgg_cd = :sgg_code
         ORDER BY {order_by_clause(sort)}
         LIMIT :limit OFFSET :offset
    """)  # noqa: S608 — ORDER BY는 _ORDER_BY 표에서만 오고 사용자 입력이 아니다
    return [
        dict(row)
        for row in connection.execute(
            statement, {"sgg_code": sgg_code, "limit": limit, "offset": offset}
        ).mappings()
    ]


__all__ = [
    "build_region_trade_page",
    "fetch_region_name",
    "fetch_region_trade_count",
    "fetch_region_trade_rows",
    "order_by_clause",
]
