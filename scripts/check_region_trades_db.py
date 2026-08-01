#!/usr/bin/env python
"""실제 DB가 db_schema_realestate.md와 맞는지 확인한다(읽기 전용).

    python scripts/check_region_trades_db.py 11680

터널을 먼저 열어야 한다 — docs/LOCAL_DB_TUNNEL.md 참고.

자동 테스트는 전부 가짜 커넥션 기반이라 SQL이 실제 뷰와 맞는지는 검증되지
않는다. 문서를 정본으로 구현하되, 정본이 틀렸을 가능성을 확인할 경로를 남긴다.
"""

import sys

from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.session import get_database_engine
from app.schemas.property_trade import TradeSort
from app.services.region_trade import load_region_trades

# 화면이 쓰는 v_valid_trades 컬럼.
EXPECTED_COLUMNS = {
    "id",
    "sgg_cd",
    "apt_nm",
    "umd_nm",
    "road_nm",
    "build_year",
    "exclu_use_ar",
    "floor",
    "contract_date",
    "deal_amount_won",
}


def main(sgg_code: str) -> int:
    config = get_settings()
    print(f"공급자    : {config.region_price_provider}")
    print(f"접속 대상 : {config.database_host}:{config.database_port}/{config.database_name}")
    print("(비밀번호는 출력하지 않습니다)\n")

    engine = get_database_engine()
    with engine.connect() as connection:
        print("1) 연결 : OK")

        inspector = inspect(engine)
        objects = (
            set(inspector.get_table_names())
            | set(inspector.get_view_names())
            | set(inspector.get_materialized_view_names())
        )
        for name in ("sgg_codes", "v_valid_trades"):
            print(f"2) {name:16s}: {'OK' if name in objects else '없음'}")
        if "v_valid_trades" not in objects:
            print("\nv_valid_trades가 없습니다. 적재 상태를 확인하세요.")
            return 1

        actual = {column["name"] for column in inspector.get_columns("v_valid_trades")}
        missing = EXPECTED_COLUMNS - actual
        print(f"3) 컬럼 일치     : {'OK' if not missing else '불일치'}")
        if missing:
            print(f"   기대했으나 없음 : {sorted(missing)}")
            print(f"   실제 컬럼       : {sorted(actual)}")
            return 1

        total = connection.execute(text("SELECT count(*) FROM v_valid_trades")).scalar_one()
        print(f"4) 유효 거래 총계 : {total:,}건")

    page = load_region_trades(sgg_code, sort=TradeSort.AREA_ASC, page=1, page_size=5)
    print(
        f"\n5) {page.sgg_name}({page.sgg_code}) · "
        f"{page.total_count:,}건 · {page.total_pages:,}페이지"
    )
    print("   [1페이지 · 좁은 면적 순]")
    for trade in page.trades:
        road = f" · {trade.road_name}" if trade.road_name else ""
        print(
            f"   {trade.apt_name[:16]:16s} {trade.umd_name}{road} · {trade.build_year}년\n"
            f"       {float(trade.exclusive_area_m2):6.2f}㎡ · {trade.floor:>3}층 · "
            f"{trade.contract_date} · {trade.deal_amount_won:>15,}원"
        )
    return 0


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "11680"
    try:
        # SystemExit는 BaseException이라 아래 except Exception에 걸리지 않는다.
        raise SystemExit(main(code))
    except Exception as exc:  # noqa: BLE001 — 운영 도구이므로 원인을 그대로 보여준다
        print(f"\n실패: {type(exc).__name__}: {exc}")
        print(
            "터널이 열려 있는지(pg_isready -h localhost -p 15432), "
            ".env의 REGION_PRICE_PROVIDER=database 인지 확인하세요."
        )
        raise SystemExit(1) from exc
