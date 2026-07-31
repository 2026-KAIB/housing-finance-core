from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.routes.properties import get_region_price_reference_loader
from app.core.config import settings
from app.main import app
from app.schemas.property_price import AreaBand, RegionPriceBand, RegionPriceReference
from app.services.region_price import RegionNotFound, RegionPriceUnavailable

SEOUL = ZoneInfo("Asia/Seoul")
PRICE_URL = f"{settings.api_prefix}/properties/price-reference"

REFERENCE = RegionPriceReference(
    sgg_code="11680",
    sgg_name="강남구",
    computed_at=datetime(2026, 7, 30, 9, 0, tzinfo=SEOUL),
    bands=(
        RegionPriceBand(
            area_band=AreaBand.LT40,
            trade_count=87,
            median_price_won=920_000_000,
            p25_price_won=800_000_000,
            p75_price_won=1_050_000_000,
            median_price_per_pyeong_won=25_000_000,
            is_reliable=True,
        ),
    ),
)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _override(loader) -> None:
    app.dependency_overrides[get_region_price_reference_loader] = lambda: loader


def test_returns_reference_for_a_seoul_district(client) -> None:
    _override(lambda sgg_code: REFERENCE)

    response = client.get(PRICE_URL, params={"sgg_code": "11680"})

    assert response.status_code == 200
    body = response.json()
    assert body["sgg_name"] == "강남구"
    assert body["stat_level"] == "sgg_all"
    assert body["schema_version"] == "1.0.0"
    assert body["bands"][0]["area_band"] == "lt40"
    assert body["bands"][0]["median_price_won"] == 920_000_000


@pytest.mark.parametrize("bad_code", ["ALL", "26440", "abc", "1168", "116800"])
def test_rejects_codes_that_are_not_seoul_district_codes(client, bad_code) -> None:
    response = client.get(PRICE_URL, params={"sgg_code": bad_code})

    assert response.status_code == 422


def test_missing_sgg_code_is_rejected(client) -> None:
    assert client.get(PRICE_URL).status_code == 422


def test_unknown_district_returns_404(client) -> None:
    def loader(sgg_code: str):
        raise RegionNotFound(sgg_code)

    _override(loader)

    response = client.get(PRICE_URL, params={"sgg_code": "11999"})

    assert response.status_code == 404


def test_unavailable_provider_returns_503(client) -> None:
    def loader(sgg_code: str):
        raise RegionPriceUnavailable("host=secret-db user=secret")

    _override(loader)

    response = client.get(PRICE_URL, params={"sgg_code": "11680"})

    assert response.status_code == 503
    # 접속 정보가 예외 메시지를 타고 응답 본문으로 나가면 안 된다.
    assert "secret" not in response.json()["detail"]


def test_district_without_stats_returns_200_with_empty_bands(client) -> None:
    empty = RegionPriceReference(sgg_code="11110", sgg_name="종로구", bands=())
    _override(lambda sgg_code: empty)

    response = client.get(PRICE_URL, params={"sgg_code": "11110"})

    assert response.status_code == 200
    body = response.json()
    assert body["bands"] == []
    assert body["computed_at"] is None
