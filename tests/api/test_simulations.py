from fastapi.testclient import TestClient

from app.main import app


def _request_body(*, emergency_reserve: int | None = 2_000_000) -> dict:
    return {
        "profile": {
            "age": 30,
            "household_size": 1,
            "annual_income": "48000000",
            "employment_type": "salaried",
            "is_first_home_buyer": True,
        },
        "housing_goal": {
            "goal_type": "HOME_PURCHASE",
            "target_amount": "300000000",
            "target_date": "2030-12-31",
            "region_code": "11620",
        },
        "financial_snapshot": {
            "monthly_income": "3500000",
            "monthly_expense": "1800000",
            "liquid_assets": "10000000",
            "housing_assets": "0",
            "total_debt": "5000000",
            "monthly_debt_payment": "200000",
            "emergency_reserve": (None if emergency_reserve is None else str(emergency_reserve)),
        },
    }


def test_simulation_endpoint_returns_connected_cashflow_section() -> None:
    response = TestClient(app).post(
        "/api/v1/simulations",
        json=_request_body(),
    )

    assert response.status_code == 200
    result = response.json()
    assert result["cashflow"]["run_status"] == "COMPLETED"
    assert result["cashflow"]["engine_status"] == "PARTIAL"
    assert result["cashflow"]["result"]["diagnosis"]["safe_monthly_income"] == "3500000"
    assert (
        result["cashflow"]["result"]["allocation"]["monthly_housing_savings_available"] is not None
    )
    assert result["savings_portfolio"]["run_status"] == "NOT_RUN"
    assert result["loan_simulation"]["run_status"] == "NOT_RUN"
    assert any("현금흐름" in warning for warning in result["warnings"])


def test_simulation_endpoint_preserves_unknown_emergency_reserve() -> None:
    response = TestClient(app).post(
        "/api/v1/simulations",
        json=_request_body(emergency_reserve=None),
    )

    assert response.status_code == 200
    cashflow = response.json()["cashflow"]
    assert cashflow["result"]["emergency_fund"]["current_amount"] is None
    assert cashflow["result"]["emergency_fund"]["shortfall_amount"] is None
    assert cashflow["result"]["allocation"]["monthly_housing_savings_available"] is None


def test_simulation_endpoint_rejects_reserve_above_liquid_assets() -> None:
    response = TestClient(app).post(
        "/api/v1/simulations",
        json=_request_body(emergency_reserve=20_000_000),
    )

    assert response.status_code == 422
    assert "liquid_assets" in str(response.json()["detail"])
