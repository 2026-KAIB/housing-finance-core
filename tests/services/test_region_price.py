from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.services.region_price import (
    RegionNotFound,
    RegionPriceUnavailable,
    load_region_price_reference,
)

SEOUL = ZoneInfo("Asia/Seoul")

ROWS = [
    {
        "area_band": "60_85",
        "trade_cnt": 342,
        "median_price_won": 2_280_000_000,
        "p25_price_won": 1_900_000_000,
        "p75_price_won": 2_700_000_000,
        "median_ppp_won": 30_000_000,
        "is_reliable": True,
        "computed_at": datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL),
    }
]


class FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def mappings(self) -> list:
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeConnection:
    """execute 호출 순서대로 준비된 결과를 돌려준다(1: 구 이름, 2: 시세 행)."""

    def __init__(self, results: list[FakeResult]) -> None:
        self._results = results
        self.executed: list[dict] = []

    def execute(self, _statement, parameters=None):
        self.executed.append(parameters or {})
        return self._results.pop(0)

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args) -> None:
        return None


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> FakeConnection:
        return self._connection


class BrokenEngine:
    def connect(self):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def _config(provider: str) -> Settings:
    return Settings(_env_file=None, region_price_provider=provider)


def test_disabled_provider_raises_unavailable() -> None:
    with pytest.raises(RegionPriceUnavailable):
        load_region_price_reference("11680", config=_config("disabled"))


def test_database_provider_returns_reference() -> None:
    connection = FakeConnection([FakeResult(["강남구"]), FakeResult(ROWS)])

    reference = load_region_price_reference(
        "11680", config=_config("database"), engine=FakeEngine(connection)
    )

    assert reference.sgg_name == "강남구"
    assert reference.bands[0].median_price_won == 2_280_000_000
    # 두 쿼리 모두 같은 코드로 파라미터 바인딩됐는지 확인한다.
    assert connection.executed == [{"sgg_code": "11680"}, {"sgg_code": "11680"}]


def test_unknown_region_raises_not_found() -> None:
    connection = FakeConnection([FakeResult([])])

    with pytest.raises(RegionNotFound):
        load_region_price_reference(
            "11999", config=_config("database"), engine=FakeEngine(connection)
        )


def test_known_region_without_stats_returns_empty_bands() -> None:
    connection = FakeConnection([FakeResult(["종로구"]), FakeResult([])])

    reference = load_region_price_reference(
        "11110", config=_config("database"), engine=FakeEngine(connection)
    )

    # 없는 구(RegionNotFound)와 구별돼야 한다 — 이쪽은 정상 응답이다.
    assert reference.sgg_name == "종로구"
    assert reference.bands == ()
    assert reference.computed_at is None


def test_connection_failure_raises_unavailable() -> None:
    with pytest.raises(RegionPriceUnavailable):
        load_region_price_reference("11680", config=_config("database"), engine=BrokenEngine())


def test_not_found_is_not_swallowed_as_unavailable() -> None:
    """RegionNotFound가 DB 오류 처리에 휩쓸리면 404가 503으로 뭉개진다."""
    connection = FakeConnection([FakeResult([])])

    with pytest.raises(RegionNotFound):
        load_region_price_reference(
            "11999", config=_config("database"), engine=FakeEngine(connection)
        )
