from datetime import date
from decimal import Decimal

import pytest

from app.db.repositories.region_trade_repository import (
    build_region_trade_page,
    order_by_clause,
)
from app.schemas.property_trade import TradeSort


def _row(**overrides) -> dict:
    """v_valid_trades 한 행의 형태를 그대로 따른다."""
    row = {
        "id": 1,
        "apt_nm": "개포주공1단지",
        "umd_nm": "개포동",
        "road_nm": "언주로",
        "build_year": 1982,
        "exclu_use_ar": Decimal("34.4400"),
        "floor": 5,
        "contract_date": date(2026, 3, 14),
        "deal_amount_won": 2_250_000_000,
    }
    row.update(overrides)
    return row


def test_maps_view_columns_to_contract_names() -> None:
    page = build_region_trade_page(
        "11680", "강남구", TradeSort.AREA_ASC, page=1, page_size=5,
        total_count=1, rows=[_row()],
    )

    trade = page.trades[0]
    assert trade.trade_id == 1
    assert trade.apt_name == "개포주공1단지"
    assert trade.umd_name == "개포동"
    assert trade.road_name == "언주로"
    assert trade.build_year == 1982
    assert trade.exclusive_area_m2 == Decimal("34.4400")
    assert trade.floor == 5
    assert trade.contract_date == date(2026, 3, 14)
    assert trade.deal_amount_won == 2_250_000_000


def test_missing_road_name_is_allowed() -> None:
    # v_valid_trades에 road_nm이 NULL인 행이 159건 있다.
    page = build_region_trade_page(
        "11680", "강남구", TradeSort.AREA_ASC, page=1, page_size=5,
        total_count=1, rows=[_row(road_nm=None)],
    )

    assert page.trades[0].road_name is None


def test_basement_floor_is_allowed() -> None:
    # 지하 거래가 10건 존재한다. 부호 없는 검증을 걸면 조회가 통째로 실패한다.
    page = build_region_trade_page(
        "11680", "강남구", TradeSort.AREA_ASC, page=1, page_size=5,
        total_count=1, rows=[_row(floor=-1)],
    )

    assert page.trades[0].floor == -1


def test_total_pages_rounds_up() -> None:
    page = build_region_trade_page(
        "11350", "노원구", TradeSort.AREA_ASC, page=1, page_size=5,
        total_count=7483, rows=[_row()],
    )

    assert page.total_count == 7483
    assert page.total_pages == 1497


def test_empty_result_has_one_page_not_zero() -> None:
    page = build_region_trade_page(
        "11110", "종로구", TradeSort.AREA_ASC, page=1, page_size=5,
        total_count=0, rows=[],
    )

    # 0페이지라고 하면 화면이 "1 / 0 페이지"를 그린다.
    assert page.total_pages == 1
    assert page.trades == ()


def test_carries_sort_and_paging_back_to_the_caller() -> None:
    page = build_region_trade_page(
        "11680", "강남구", TradeSort.PRICE_DESC, page=3, page_size=5,
        total_count=100, rows=[_row()],
    )

    assert page.sort == TradeSort.PRICE_DESC
    assert page.page == 3
    assert page.page_size == 5
    assert page.sgg_code == "11680"
    assert page.sgg_name == "강남구"


class TestOrderByClause:
    """정렬 문자열은 열거형에서만 나오고, 항상 유일한 보조키로 끝나야 한다."""

    def test_every_sort_option_is_mapped(self) -> None:
        for sort in TradeSort:
            assert order_by_clause(sort)

    def test_every_clause_ends_with_the_unique_tiebreaker(self) -> None:
        # 면적·가격은 동점이 흔하다. 전순서가 아니면 같은 거래가 두 페이지에
        # 나오거나 어느 페이지에도 나오지 않는다.
        for sort in TradeSort:
            assert order_by_clause(sort).strip().endswith("id ASC")

    def test_clauses_use_the_expected_columns(self) -> None:
        assert order_by_clause(TradeSort.AREA_ASC).startswith("exclu_use_ar ASC")
        assert order_by_clause(TradeSort.AREA_DESC).startswith("exclu_use_ar DESC")
        assert order_by_clause(TradeSort.PRICE_ASC).startswith("deal_amount_won ASC")
        assert order_by_clause(TradeSort.PRICE_DESC).startswith("deal_amount_won DESC")

    def test_rejects_anything_that_is_not_a_known_sort(self) -> None:
        with pytest.raises(KeyError):
            order_by_clause("exclu_use_ar; DROP TABLE apt_trades")  # type: ignore[arg-type]
