import pytest
from fastapi.testclient import TestClient

from app.api.routes import health
from app.main import app
from app.services.loan_product_catalog import LoanProductCatalogUnavailable


def test_health_check() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_the_configured_product_provider() -> None:
    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["loan_product_provider"] == "json"
    assert isinstance(response.json()["loan_product_count"], int)


def test_readiness_returns_503_when_the_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_provider(*args: object, **kwargs: object) -> tuple[()]:
        raise LoanProductCatalogUnavailable("unavailable")

    monkeypatch.setattr(health, "load_configured_loan_candidates", fail_provider)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert "준비되지 않았습니다" in response.json()["detail"]
