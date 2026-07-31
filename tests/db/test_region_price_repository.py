from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.db.repositories.region_price_repository import build_region_price_reference
from app.schemas.property_price import AreaBand

SEOUL = ZoneInfo("Asia/Seoul")
COMPUTED_AT = datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL)


def _row(area_band: str, median: int, *, reliable: bool = True) -> dict:
    """db_schema_realestate.md §8의 apt_price_stats 행 형태를 그대로 따른다."""
    return {
        "area_band": area_band,
        "trade_cnt": 120,
        "median_price_won": median,
        "p25_price_won": median - 100_000_000,
        "p75_price_won": median + 100_000_000,
        "median_ppp_won": 30_000_000,
        "is_reliable": reliable,
        "computed_at": COMPUTED_AT,
    }


def test_bands_are_ordered_by_area_not_alphabetically() -> None:
    # DB가 사전순으로 돌려준 상태를 흉내낸다. 사전순이면 lt40이 맨 뒤로 간다.
    rows = [
        _row("40_60", 1_400_000_000),
        _row("60_85", 2_200_000_000),
        _row("85_135", 3_100_000_000),
        _row("gte135", 4_500_000_000),
        _row("lt40", 900_000_000),
    ]

    reference = build_region_price_reference("11680", "강남구", rows)

    assert [band.area_band for band in reference.bands] == [
        AreaBand.LT40,
        AreaBand.A40_60,
        AreaBand.A60_85,
        AreaBand.A85_135,
        AreaBand.GTE135,
    ]


def test_maps_db_columns_to_contract_names() -> None:
    reference = build_region_price_reference("11680", "강남구", [_row("60_85", 2_200_000_000)])

    band = reference.bands[0]
    assert band.trade_count == 120
    assert band.median_price_won == 2_200_000_000
    assert band.p25_price_won == 2_100_000_000
    assert band.p75_price_won == 2_300_000_000
    assert band.median_price_per_pyeong_won == 30_000_000
    assert band.is_reliable is True


def test_carries_region_identity_and_computed_at() -> None:
    reference = build_region_price_reference("11680", "강남구", [_row("60_85", 2_200_000_000)])

    assert reference.sgg_code == "11680"
    assert reference.sgg_name == "강남구"
    assert reference.stat_level == "sgg_all"
    assert reference.schema_version == "1.0.0"
    assert reference.computed_at == COMPUTED_AT


def test_empty_rows_produce_empty_bands_without_computed_at() -> None:
    reference = build_region_price_reference("11680", "강남구", [])

    assert reference.bands == ()
    assert reference.computed_at is None
    assert reference.sgg_name == "강남구"


def test_unreliable_band_is_kept_with_its_flag() -> None:
    reference = build_region_price_reference(
        "11110", "종로구", [_row("gte135", 4_000_000_000, reliable=False)]
    )

    # 숨기지 않는다 — 5줄이어야 할 표가 4줄로 나오는 이유를 화면이 설명할 수 없다.
    assert len(reference.bands) == 1
    assert reference.bands[0].is_reliable is False


def test_median_price_per_pyeong_may_be_missing() -> None:
    row = _row("60_85", 2_200_000_000)
    row["median_ppp_won"] = None

    reference = build_region_price_reference("11680", "강남구", [row])

    assert reference.bands[0].median_price_per_pyeong_won is None


def test_unknown_area_band_is_rejected() -> None:
    # 스키마에 없는 구간이 조용히 통과하면 화면에 라벨 없는 행이 생긴다.
    with pytest.raises(ValueError):
        build_region_price_reference("11680", "강남구", [_row("30_40", 500_000_000)])
