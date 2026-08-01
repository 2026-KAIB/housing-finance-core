from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.routes.properties import get_region_trades_loader
from app.core.config import settings
from app.main import app
from app.schemas.property_trade import RegionTrade, RegionTradePage, TradeSort
from app.services.region_trade import RegionNotFound, RegionTradesUnavailable

TRADES_URL = f"{settings.api_prefix}/properties/trades"

TRADE = RegionTrade(
    trade_id=42,
    apt_name="개포주공1단지",
    umd_name="개포동",
    road_name="언주로",
    build_year=1982,
    exclusive_area_m2=Decimal("34.4400"),
    floor=5,
    contract_date=date(2026, 3, 14),
    deal_amount_won=2_250_000_000,
)


def _page(**overrides) -> RegionTradePage:
    values = {
        "sgg_code": "11680",
        "sgg_name": "강남구",
        "sort": TradeSort.AREA_ASC,
        "page": 1,
        "page_size": 5,
        "total_count": 100,
        "total_pages": 20,
        "trades": (TRADE,),
    }
    values.update(overrides)
    return RegionTradePage(**values)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(loader) -> None:
    app.dependency_overrides[get_region_trades_loader] = lambda: loader


def test_returns_a_page_of_trades(client) -> None:
    _override(lambda code, **_: _page())

    response = client.get(TRADES_URL, params={"sgg_code": "11680"})

    assert response.status_code == 200
    body = response.json()
    assert body["sgg_name"] == "강남구"
    assert body["total_count"] == 100
    assert body["total_pages"] == 20
    assert body["trades"][0]["apt_name"] == "개포주공1단지"
    assert body["trades"][0]["umd_name"] == "개포동"
    assert body["trades"][0]["road_name"] == "언주로"
    assert body["trades"][0]["build_year"] == 1982
    assert body["trades"][0]["floor"] == 5
    assert body["trades"][0]["contract_date"] == "2026-03-14"
    assert body["trades"][0]["deal_amount_won"] == 2_250_000_000


def test_defaults_are_area_ascending_page_one_size_five(client) -> None:
    seen: dict = {}

    def loader(code, **kwargs):
        seen.update(kwargs)
        return _page()

    _override(loader)
    client.get(TRADES_URL, params={"sgg_code": "11680"})

    assert seen == {"sort": TradeSort.AREA_ASC, "page": 1, "page_size": 5}


@pytest.mark.parametrize(
    "sort", ["area_asc", "area_desc", "price_asc", "price_desc"]
)
def test_accepts_every_sort_option(client, sort) -> None:
    seen: dict = {}

    def loader(code, **kwargs):
        seen.update(kwargs)
        return _page(sort=TradeSort(sort))

    _override(loader)
    response = client.get(TRADES_URL, params={"sgg_code": "11680", "sort": sort})

    assert response.status_code == 200
    assert seen["sort"] == TradeSort(sort)


@pytest.mark.parametrize(
    "params",
    [
        {"sgg_code": "ALL"},
        {"sgg_code": "26440"},
        {"sgg_code": "abc"},
        {"sgg_code": "11680", "sort": "cheapest"},
        {"sgg_code": "11680", "page": 0},
        {"sgg_code": "11680", "page_size": 0},
        {"sgg_code": "11680", "page_size": 51},
    ],
)
def test_rejects_invalid_query(client, params) -> None:
    assert client.get(TRADES_URL, params=params).status_code == 422


def test_unknown_district_returns_404(client) -> None:
    def loader(code, **_):
        raise RegionNotFound(code)

    _override(loader)

    assert client.get(TRADES_URL, params={"sgg_code": "11999"}).status_code == 404


def test_unavailable_provider_returns_503(client) -> None:
    def loader(code, **_):
        raise RegionTradesUnavailable("host=secret-db user=secret")

    _override(loader)
    response = client.get(TRADES_URL, params={"sgg_code": "11680"})

    assert response.status_code == 503
    # 접속 정보가 예외 메시지를 타고 응답 본문으로 나가면 안 된다.
    assert "secret" not in response.json()["detail"]


def test_page_past_the_end_is_200_with_an_empty_list(client) -> None:
    _override(lambda code, **_: _page(page=99, total_count=7, total_pages=2, trades=()))

    response = client.get(TRADES_URL, params={"sgg_code": "11680", "page": 99})

    # 목록의 끝은 오류가 아니다.
    assert response.status_code == 200
    assert response.json()["trades"] == []


def test_missing_road_name_serializes_as_null(client) -> None:
    _override(lambda code, **_: _page(trades=(TRADE.model_copy(update={"road_name": None}),)))

    response = client.get(TRADES_URL, params={"sgg_code": "11680"})

    assert response.json()["trades"][0]["road_name"] is None


def test_price_reference_endpoint_is_gone(client) -> None:
    response = client.get(
        f"{settings.api_prefix}/properties/price-reference",
        params={"sgg_code": "11680"},
    )

    assert response.status_code == 404
