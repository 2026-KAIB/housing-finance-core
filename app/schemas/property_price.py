"""지역 시세 통계 계약.

`property.py`(매물 목록)와 별도 파일인 이유는 데이터의 성격이 다르기 때문이다.
이 DB에는 판매 중인 매물이 없고(`apt_trades`는 체결 이력, 동·호수 없음),
여기서 다루는 것은 실거래에서 집계한 통계다.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

REGION_PRICE_SCHEMA_VERSION = "1.0.0"


class AreaBand(StrEnum):
    """전용면적 구간. **선언 순서가 곧 크기 순서**이며 정렬의 정본이다.

    값 문자열을 사전순으로 정렬하면
    `40_60 < 60_85 < 85_135 < gte135 < lt40`이 되어 가장 작은 평형이 맨 뒤로
    간다. 그래서 SQL `ORDER BY area_band`를 쓰지 않는다.

    85㎡ 경계는 임의가 아니다 — 디딤돌·보금자리론이 전용 85㎡ 이하를 요건으로
    걸기 때문에, 시세 조회 결과가 그대로 대출상품 필터의 입력이 된다.
    """

    LT40 = "lt40"
    A40_60 = "40_60"
    A60_85 = "60_85"
    A85_135 = "85_135"
    GTE135 = "gte135"


class RegionPriceBand(BaseModel):
    """한 평형 구간의 시세. 금액은 모두 원 단위 정수다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    area_band: AreaBand
    trade_count: int = Field(ge=0)
    median_price_won: int = Field(gt=0)
    p25_price_won: int = Field(gt=0)
    p75_price_won: int = Field(gt=0)
    # 전용면적 기준이다. 시장에서 통용되는 평단가는 공급면적 기준이라 이 값보다
    # 20~30% 낮게 나오므로, 화면에 낼 때 반드시 "전용 기준"을 함께 표기한다.
    median_price_per_pyeong_won: int | None = Field(default=None, gt=0)
    # 표본 5건 이상 + 최신 2개월이 아님. false여도 숨기지 않고 함께 표시한다.
    is_reliable: bool


class RegionPriceReference(BaseModel):
    """한 자치구의 평형대별 시세. `stat_level='sgg_all'` 기준."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = REGION_PRICE_SCHEMA_VERSION
    sgg_code: str = Field(pattern=r"^\d{5}$")
    sgg_name: str = Field(min_length=1)
    # 어느 단위의 숫자인지 화면이 말할 수 있어야 한다("데이터 기준일 표시" 원칙).
    stat_level: Literal["sgg_all"] = "sgg_all"
    # 통계 행이 하나도 없으면 기준일도 없다.
    computed_at: datetime | None = None
    bands: tuple[RegionPriceBand, ...] = ()


__all__ = [
    "REGION_PRICE_SCHEMA_VERSION",
    "AreaBand",
    "RegionPriceBand",
    "RegionPriceReference",
]
