from fastapi.testclient import TestClient

from app.main import app


def _payload() -> dict[str, object]:
    return {
        "criteria": {
            "region_codes": ["11620"],
            "transaction_type": "SALE",
            "property_types": ["VILLA"],
            "max_price_krw": "50000000",
            "max_station_walk_minutes": 10,
            "sort": "PRICE_ASC",
        },
        "profile": {
            "persona_name": "PRIVATE-PERSONA",
            "age": 30,
            "annual_income": "60000000",
            "is_first_home_buyer": True,
        },
        "financial_snapshot": {
            "monthly_income": "5000000",
            "monthly_expense": "2000000",
            "liquid_assets": "100000000",
            "monthly_debt_payment": "0",
            "emergency_reserve": "6000000",
        },
        "acquisition_profile": {
            "buyer_is_corporation": False,
            "household_home_count_after_purchase": 1,
            "default_property_facts": {
                "is_registered_housing": True,
                "is_luxury_home": False,
                "registration_and_legal_costs": "186000",
            },
        },
    }


def test_property_affordability_endpoint_connects_search_and_engines() -> None:
    response = TestClient(app).post(
        "/api/v1/properties/affordability",
        json=_payload(),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["schema_version"] == "1.0.0"
    assert result["total_count"] == 1
    assert result["verdict_counts"] == {"AFFORDABLE": 1}
    assessment = result["assessments"][0]
    assert assessment["candidate"]["listing_id"] == "MOCK-GWANAK-001"
    assert assessment["verdict"] == "AFFORDABLE"
    assert assessment["required_loan_amount"] == "0"
    assert assessment["engine_result"]["purchase_price"] == "49000000"


def test_property_affordability_endpoint_rejects_per_listing_amount_override() -> None:
    payload = _payload()
    payload["loan_request"] = {
        "months": 360,
        "housing_status": "FIRST_HOME_BUYER",
        "monthly_essential_expense": "2000000",
        "required_amount": "10000000",
    }

    response = TestClient(app).post(
        "/api/v1/properties/affordability",
        json=payload,
    )

    assert response.status_code == 422
    assert "calculated per listing" in str(response.json()["detail"])
