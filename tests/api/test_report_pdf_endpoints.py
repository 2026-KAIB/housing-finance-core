"""``format=pdf``와 ``GET /reports/{id}.pdf`` 의 HTTP 계약.

보관이 꺼진 기본 설정에서 무엇을 돌려주는지를 고정한다. 여기가 흐물흐물하면
"보관을 안 켰다"와 "PDF를 못 만들었다"와 "그런 문서가 없다"가 프론트엔드에서
같은 오류로 보인다.

WeasyPrint는 요구하지 않는다 — 보관이 꺼져 있으면 렌더링에 닿기 전에 막힌다.
"""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import DatabaseConfigurationError
from app.main import app
from app.reports.ai_explanation.gemini import GenerationResult
from app.reports.pdf import pdf_rendering_available
from app.reports.templates.form import FORM_SECTIONS

_KEYS = tuple(key for key, _title in FORM_SECTIONS)


class _FakeClient:
    def __init__(self, _settings: Any = None) -> None:
        self._settings = _settings

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> GenerationResult:
        if "판정" in system_prompt and "감수자" in system_prompt:
            return GenerationResult(
                text=json.dumps(
                    {key: {"verdict": "OK", "reason": ""} for key in _KEYS},
                    ensure_ascii=False,
                ),
                model="j",
            )
        return GenerationResult(
            text=json.dumps(
                {key: "표시된 수치가 무엇을 뜻하는지 설명합니다." for key in _KEYS},
                ensure_ascii=False,
            ),
            model="w",
        )


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.reports.ai_explanation.form_agent.GeminiClient", _FakeClient)
    monkeypatch.setattr(
        "app.reports.ai_explanation.verifier_agent.GeminiClient", _FakeClient
    )


def _simulation_payload() -> dict[str, object]:
    return {
        "profile": {"age": 34, "annual_income": "60000000", "is_first_home_buyer": True},
        "housing_goal": {
            "target_amount": "500000000",
            "target_date": "2028-08-01",
            "region_code": "11680",
        },
        "financial_snapshot": {
            "monthly_income": "5000000",
            "monthly_expense": "2000000",
            "liquid_assets": "60000000",
            "monthly_debt_payment": "300000",
            "emergency_reserve": "12000000",
        },
    }


def test_asking_for_a_pdf_while_archiving_is_off_says_so(fake_ai: None) -> None:
    """503(고장)이 아니라 501(설정 안 됨)이어야 한다. 프론트엔드가 재시도하면 안 된다."""
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/reports", params={"format": "pdf"}, json=_simulation_payload()
        )

    assert response.status_code == 501
    assert "REPORT_ARCHIVE_PROVIDER" in response.json()["detail"]


def test_reading_an_archived_report_while_archiving_is_off_says_so() -> None:
    with TestClient(app) as client:
        response = client.get(f"/api/v1/reports/{uuid4()}.pdf")

    assert response.status_code == 501


def test_a_non_uuid_report_id_is_rejected_by_the_boundary() -> None:
    """경로에서 온 값을 그대로 저장소 경로에 쓰지 않는다는 것을 경계에서 못 박는다."""
    with TestClient(app) as client:
        response = client.get("/api/v1/reports/..%2F..%2Fetc%2Fpasswd.pdf")

    assert response.status_code in {404, 422}


def test_the_print_format_still_returns_html(fake_ai: None) -> None:
    """PDF를 더하면서 기존 인쇄 경로가 바뀌지 않았는지 확인한다."""
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/reports", params={"format": "print"}, json=_simulation_payload()
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.fixture
def archiving_on_without_a_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """보관은 켜져 있고 DB에는 닿지 못하는 상태 — 개발 환경에서 가장 흔하다.

    DB를 실제로 부르지 않게 막는다. 여기서 진짜 접속을 시도하면 터널이 열려
    있는지에 따라 테스트 결과가 갈리고, 닫혀 있으면 접속 타임아웃만큼 느려진다.
    """
    monkeypatch.setattr(
        "app.services.report_archive.get_settings",
        lambda: Settings(
            report_archive_provider="filesystem", report_storage_root=tmp_path
        ),
    )

    def _no_database():
        raise DatabaseConfigurationError("no database in this test")

    monkeypatch.setattr(
        "app.services.report_archive.get_database_engine", _no_database
    )


@pytest.mark.skipif(not pdf_rendering_available(), reason="weasyprint가 없는 환경")
def test_a_pdf_is_returned_and_then_read_back_without_a_database(
    fake_ai: None, archiving_on_without_a_database: None
) -> None:
    """웹 뷰어가 실제로 쓰는 두 걸음이다: POST로 id를 받고 GET으로 그 문서를 연다.

    예전에는 첫 걸음이 503이었다 — 렌더링과 글꼴 검사를 통과해 디스크에 저장까지
    끝난 문서를, DB 색인 한 줄을 남기지 못했다는 이유로 버렸다.
    """
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/reports", params={"format": "pdf"}, json=_simulation_payload()
        )

        assert created.status_code == 200, created.text
        assert created.headers["content-type"] == "application/pdf"
        assert created.content.startswith(b"%PDF")

        report_id = created.headers["X-Report-Id"]
        fetched = client.get(f"/api/v1/reports/{report_id}.pdf")

    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "application/pdf"
    # 새로고침·새 탭 열기가 같은 문서를 열어야 한다. 다시 렌더링하면 서술이
    # 갈릴 수 있으므로 바이트가 같은지까지 본다.
    assert fetched.content == created.content


@pytest.mark.skipif(not pdf_rendering_available(), reason="weasyprint가 없는 환경")
def test_an_unknown_report_id_is_missing_not_broken(
    archiving_on_without_a_database: None,
) -> None:
    """오타 난 문서번호가 서버 장애(503)로 보이면 안 된다."""
    with TestClient(app) as client:
        response = client.get(f"/api/v1/reports/{uuid4()}.pdf")

    assert response.status_code == 404
