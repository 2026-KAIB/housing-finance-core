from fastapi.testclient import TestClient

from app.main import app


def test_property_search_endpoint_accepts_frontend_filter_values() -> None:
    response = TestClient(app).post(
        "/api/v1/properties/search",
        json={
            "region_codes": ["11620"],
            "transaction_type": "SALE",
            "property_types": ["VILLA"],
            "max_price_krw": "50000000",
            "max_station_walk_minutes": 10,
            "sort": "PRICE_ASC",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == "1.0.0"
    assert result["source"]["source_type"] == "MOCK"
    assert result["criteria"]["max_price_krw"] == "50000000"
    assert result["total_count"] == 1
    assert result["candidates"][0]["listing_id"] == "MOCK-GWANAK-001"


def test_property_search_endpoint_rejects_invalid_range() -> None:
    response = TestClient(app).post(
        "/api/v1/properties/search",
        json={
            "region_codes": ["11620"],
            "min_price_krw": "50000001",
            "max_price_krw": "50000000",
        },
    )

    assert response.status_code == 422
    assert "min_price_krw" in str(response.json()["detail"])


def test_property_search_v1_rejects_unsupported_rental_transaction() -> None:
    response = TestClient(app).post(
        "/api/v1/properties/search",
        json={
            "region_codes": ["11620"],
            "transaction_type": "JEONSE",
        },
    )

    assert response.status_code == 422
