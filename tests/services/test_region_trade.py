from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.schemas.property_trade import TradeSort
from app.services.region_trade import (
    RegionNotFound,
    RegionTradesUnavailable,
    load_region_trades,
)

ROW = {
    "id": 42,
    "apt_nm": "개포주공1단지",
    "umd_nm": "개포동",
    "road_nm": "언주로",
    "build_year": 1982,
    "exclu_use_ar": Decimal("34.4400"),
    "floor": 5,
    "contract_date": date(2026, 3, 14),
    "deal_amount_won": 2_250_000_000,
}


class FakeResult:
    def __init__(self, value) -> None:
        self._value = value

    def mappings(self) -> list:
        return self._value

    def scalar_one_or_none(self):
        return self._value[0] if self._value else None

    def scalar_one(self):
        return self._value


class FakeConnection:
    """execute 순서대로 결과를 돌려준다(1: 구 이름, 2: 총건수, 3: 행)."""

    def __init__(self, results: list[FakeResult]) -> None:
        self._results = results
        self.executed: list[dict] = []
        self.statements: list[str] = []

    def execute(self, statement, parameters=None):
        self.statements.append(str(statement))
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


def _connection(name="강남구", total=100, rows=(ROW,)) -> FakeConnection:
    return FakeConnection([FakeResult([name]), FakeResult(total), FakeResult(list(rows))])


def test_disabled_provider_raises_unavailable() -> None:
    with pytest.raises(RegionTradesUnavailable):
        load_region_trades("11680", config=_config("disabled"))


def test_returns_a_page_of_trades() -> None:
    connection = _connection()

    page = load_region_trades(
        "11680", config=_config("database"), engine=FakeEngine(connection)
    )

    assert page.sgg_name == "강남구"
    assert page.total_count == 100
    assert page.total_pages == 20
    assert page.trades[0].apt_name == "개포주공1단지"


def test_defaults_to_area_ascending_first_page() -> None:
    connection = _connection()

    page = load_region_trades(
        "11680", config=_config("database"), engine=FakeEngine(connection)
    )

    assert page.sort == TradeSort.AREA_ASC
    assert page.page == 1
    assert page.page_size == 5
    assert connection.executed[-1]["offset"] == 0
    assert connection.executed[-1]["limit"] == 5


def test_offset_follows_the_requested_page() -> None:
    connection = _connection()

    load_region_trades(
        "11680", page=4, page_size=5,
        config=_config("database"), engine=FakeEngine(connection),
    )

    assert connection.executed[-1]["offset"] == 15


def test_sort_reaches_the_order_by_clause() -> None:
    connection = _connection()

    load_region_trades(
        "11680", sort=TradeSort.PRICE_DESC,
        config=_config("database"), engine=FakeEngine(connection),
    )

    assert "deal_amount_won DESC, id ASC" in connection.statements[-1]


def test_unknown_region_raises_not_found() -> None:
    connection = FakeConnection([FakeResult([])])

    with pytest.raises(RegionNotFound):
        load_region_trades(
            "11999", config=_config("database"), engine=FakeEngine(connection)
        )


def test_page_past_the_end_returns_empty_without_error() -> None:
    connection = _connection(total=7, rows=())

    page = load_region_trades(
        "11110", page=99, config=_config("database"), engine=FakeEngine(connection)
    )

    # 목록의 끝은 오류가 아니다.
    assert page.trades == ()
    assert page.total_count == 7
    assert page.total_pages == 2


def test_connection_failure_raises_unavailable() -> None:
    with pytest.raises(RegionTradesUnavailable):
        load_region_trades("11680", config=_config("database"), engine=BrokenEngine())
