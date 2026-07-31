"""지역 실거래 목록 계약.

`property.py`(매물 목록)와 다른 데이터다. 이 DB에는 판매 중인 매물이 없고,
여기서 다루는 것은 이미 체결이 끝난 실거래 이력이다.

집계(`apt_price_stats`)가 아니라 개별 거래를 다루는 이유는 **같은 아파트·같은
면적이라도 층마다 거래가격이 다르기 때문**이다. 중위값 하나로 뭉개면 층과
가격의 짝이 끊긴다.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REGION_TRADE_SCHEMA_VERSION = "1.0.0"


class TradeSort(StrEnum):
    """화면 정렬 드롭다운과 1:1로 대응한다."""

    AREA_ASC = "area_asc"  # 좁은 면적 순 (기본값)
    AREA_DESC = "area_desc"  # 넓은 면적 순
    PRICE_ASC = "price_asc"  # 가격 낮은 순
    PRICE_DESC = "price_desc"  # 가격 높은 순


class RegionTrade(BaseModel):
    """한 건의 실거래. 한 행 = 한 거래이며 층과 가격이 같은 거래에서 온다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: int
    apt_name: str = Field(min_length=1)
    umd_name: str = Field(min_length=1)
    # v_valid_trades에 159건이 NULL이다. 단지가 복수 도로에 걸친 경우가 있어
    # 도로명은 단지가 아니라 거래 단위로 유지된다.
    road_name: str | None = None
    build_year: int
    exclusive_area_m2: Decimal = Field(gt=0)
    # 음수를 허용한다 — 지하 거래(-1)가 10건 존재한다. 부호 없는 검증을 걸면
    # 그 구의 조회가 통째로 실패한다.
    floor: int
    contract_date: date
    deal_amount_won: int = Field(gt=0)


class RegionTradePage(BaseModel):
    """한 자치구의 실거래 한 페이지."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = REGION_TRADE_SCHEMA_VERSION
    sgg_code: str = Field(pattern=r"^\d{5}$")
    sgg_name: str = Field(min_length=1)
    sort: TradeSort
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total_count: int = Field(ge=0)
    # 결과가 없어도 1이다. 0으로 두면 화면이 "1 / 0 페이지"를 그린다.
    total_pages: int = Field(ge=1)
    trades: tuple[RegionTrade, ...] = ()


__all__ = [
    "REGION_TRADE_SCHEMA_VERSION",
    "RegionTrade",
    "RegionTradePage",
    "TradeSort",
]
