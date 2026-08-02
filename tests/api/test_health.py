import pytest
from fastapi.testclient import TestClient

from app.api.routes import health
from app.core.config import settings
from app.main import app
from app.services.loan_product_catalog import LoanProductCatalogUnavailable
from app.services.region_trade import RegionTradesUnavailable


@pytest.fixture(autouse=True)
def offline_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB를 쓰는 공급자는 꺼 둔다.

    개발자 `.env`가 있으면 준비 확인이 실제 DB에 붙어, 터널을 열었는지에 따라
    같은 테스트가 통과하기도 실패하기도 한다. 공급자 설정을 여기서 고정해
    테스트가 환경에 기대지 않게 한다(`.env` 없이도 전체 통과라는 규약).
    """

    monkeypatch.setattr(health.settings, "loan_product_provider", "json")
    monkeypatch.setattr(health.settings, "savings_product_provider", "none")
    monkeypatch.setattr(health.settings, "region_price_provider", "disabled")


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


def test_readiness_is_reachable_under_the_api_prefix() -> None:
    """프론트엔드 프록시는 `/api/...`만 넘긴다. 루트에만 있으면 웹에서 못 본다."""

    response = TestClient(app).get(f"{settings.api_prefix}/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_reports_disabled_providers_without_failing() -> None:
    """꺼진 공급자는 설정으로 고른 상태이므로 준비 실패가 아니다."""

    response = TestClient(app).get("/ready")

    providers = response.json()["providers"]
    assert response.status_code == 200
    assert providers["region_price"]["status"] == "disabled"
    assert providers["savings_product"]["status"] == "disabled"


def test_readiness_returns_503_when_an_enabled_provider_cannot_be_queried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실거래 공급자만 죽어도 배포가 '준비됨'으로 통과하면 안 된다."""

    monkeypatch.setattr(health.settings, "region_price_provider", "database")

    def fail_probe() -> None:
        raise RegionTradesUnavailable("unavailable")

    monkeypatch.setattr(health, "probe_region_trades", fail_probe)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["providers"]["region_price"]["status"] == "error"
    assert response.json()["providers"]["loan_product"]["status"] == "ok"
    assert "region_price" in response.json()["detail"]


def test_readiness_returns_503_when_the_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_provider(*args: object, **kwargs: object) -> tuple[()]:
        raise LoanProductCatalogUnavailable("unavailable")

    monkeypatch.setattr(health, "load_configured_loan_candidates", fail_provider)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert "준비되지 않았습니다" in response.json()["detail"]
