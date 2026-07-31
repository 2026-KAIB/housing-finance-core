#!/usr/bin/env python
"""실제 DB가 db_schema_realestate.md와 맞는지 확인한다(읽기 전용).

    python scripts/check_region_price_db.py 11680

터널을 먼저 열어야 한다 — docs/LOCAL_DB_TUNNEL.md 참고.

이 스크립트가 필요한 이유: 자동 테스트는 전부 가짜 커넥션 기반이라 SQL이 실제
테이블과 맞는지는 검증되지 않는다. 문서를 정본으로 구현하되, 정본이 틀렸을
가능성을 확인할 경로를 남긴다.
"""

import sys

from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.db.session import get_database_engine
from app.services.region_price import load_region_price_reference

# db_schema_realestate.md §8이 정의한 apt_price_stats 컬럼.
EXPECTED_COLUMNS = {
    "stat_level",
    "scope_type",
    "scope_cd",
    "lawd_cd",
    "sgg_cd",
    "area_band",
    "period_key",
    "trade_cnt",
    "median_price_won",
    "p25_price_won",
    "p75_price_won",
    "median_ppp_won",
    "is_reliable",
    "computed_at",
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
        # apt_price_stats는 MATERIALIZED VIEW다. PostgreSQL에서 get_view_names()는
        # 일반 뷰만 돌려주므로, 이것만 보면 존재하는 객체를 "없음"으로 오판한다.
        objects = (
            set(inspector.get_table_names())
            | set(inspector.get_view_names())
            | set(inspector.get_materialized_view_names())
        )
        for name in ("sgg_codes", "apt_price_stats"):
            print(f"2) {name:16s}: {'OK' if name in objects else '없음'}")
        if "apt_price_stats" not in objects:
            print("\napt_price_stats가 없습니다. 적재 상태를 확인하세요.")
            return 1

        actual = {column["name"] for column in inspector.get_columns("apt_price_stats")}
        missing = EXPECTED_COLUMNS - actual
        print(f"3) 컬럼 일치     : {'OK' if not missing else '불일치'}")
        if missing:
            print(f"   문서에 있으나 DB에 없음 : {sorted(missing)}")
            print(f"   DB의 실제 컬럼          : {sorted(actual)}")
            return 1

        count = connection.execute(
            text("SELECT count(*) FROM apt_price_stats WHERE stat_level = 'sgg_all'")
        ).scalar_one()
        print(f"4) sgg_all 행수  : {count} (문서 기준 125)")

    reference = load_region_price_reference(sgg_code)
    print(f"\n5) {reference.sgg_name}({reference.sgg_code}) · 기준 {reference.computed_at}")
    if not reference.bands:
        print("   통계 행이 없습니다.")
    for band in reference.bands:
        flag = "" if band.is_reliable else "  [표본 부족]"
        print(
            f"   {band.area_band.value:8s} "
            f"중위 {band.median_price_won:>15,}원  "
            f"{band.trade_count:>5}건{flag}"
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
