"""`apt_price_stats`에서 자치구 단위 시세를 읽는다(읽기 전용).

컬럼명의 정본은 `db_schema_realestate.md` §1·§8이다. 이 파일이 DB 컬럼명을
아는 유일한 계층이며, 위 계층은 계약(`property_price.py`)의 이름만 안다.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.schemas.property_price import AreaBand, RegionPriceBand, RegionPriceReference

# 구 존재 확인과 시세 조회를 나눈 이유: 한 번의 JOIN으로 합치면 결과가 0행일 때
# "없는 구"와 "통계가 아직 없는 구"를 구별할 수 없다. 화면이 두 경우에 다른 말을
# 해야 하므로 원인을 여기서 갈라 준다. 두 쿼리 모두 PK/UNIQUE 인덱스를 탄다.
_REGION_NAME_SQL = text("""
    SELECT sgg_nm
      FROM sgg_codes
     WHERE sgg_cd = :sgg_code
""")

# UNIQUE (stat_level, scope_cd, area_band, period_key) 위에서 도는 조회다.
# sgg_all 행에서는 scope_cd = sgg_cd이고 period_key = 'ALL'이다.
_REGION_PRICE_SQL = text("""
    SELECT area_band,
           trade_cnt,
           median_price_won,
           p25_price_won,
           p75_price_won,
           median_ppp_won,
           is_reliable,
           computed_at
      FROM apt_price_stats
     WHERE stat_level = 'sgg_all'
       AND scope_cd = :sgg_code
""")

# 크기 순서. AreaBand 선언 순서가 정본이므로 여기서 다시 나열하지 않는다.
_AREA_BAND_ORDER = {band: index for index, band in enumerate(AreaBand)}


def build_region_price_reference(
    sgg_code: str,
    sgg_name: str,
    rows: Sequence[Mapping[str, Any]],
) -> RegionPriceReference:
    """조회 행을 계약으로 바꾼다(순수 함수).

    DB 접속 없이 매핑과 정렬을 검증할 수 있도록 I/O와 분리했다
    (`build_loan_candidates`와 같은 이유).
    """
    bands = [
        RegionPriceBand(
            area_band=AreaBand(row["area_band"]),
            trade_count=row["trade_cnt"],
            median_price_won=row["median_price_won"],
            p25_price_won=row["p25_price_won"],
            p75_price_won=row["p75_price_won"],
            median_price_per_pyeong_won=row["median_ppp_won"],
            is_reliable=row["is_reliable"],
        )
        for row in rows
    ]
    bands.sort(key=lambda band: _AREA_BAND_ORDER[band.area_band])

    return RegionPriceReference(
        sgg_code=sgg_code,
        sgg_name=sgg_name,
        # 같은 리프레시에서 나온 행들이므로 어느 행을 봐도 같다.
        computed_at=rows[0]["computed_at"] if rows else None,
        bands=tuple(bands),
    )


def fetch_region_name(connection: Connection, sgg_code: str) -> str | None:
    """`sgg_codes`에 있으면 구 이름을, 없으면 None을 돌려준다."""
    return connection.execute(_REGION_NAME_SQL, {"sgg_code": sgg_code}).scalar_one_or_none()


def fetch_region_price_rows(connection: Connection, sgg_code: str) -> list[dict[str, Any]]:
    """자치구 단위 시세 행을 정렬 없이 그대로 읽는다(정렬은 계약 순서로 한다)."""
    return [
        dict(row)
        for row in connection.execute(_REGION_PRICE_SQL, {"sgg_code": sgg_code}).mappings()
    ]


__all__ = [
    "build_region_price_reference",
    "fetch_region_name",
    "fetch_region_price_rows",
]
