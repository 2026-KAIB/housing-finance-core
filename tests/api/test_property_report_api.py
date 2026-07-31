"""``POST /api/v1/reports/property`` — 검색·계산·핸드오프·보고서를 한 요청으로.

AI 호출은 가짜 생성기로 대체한다. 개발자 환경에 ``GEMINI_API_KEY``가 있으면
테스트가 실제 네트워크를 쓰게 되므로 클라이언트 자체를 갈아 끼운다.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reports.ai_explanation.gemini import GenerationResult
from app.reports.templates.property_form import PROPERTY_FORM_SECTIONS

_KEYS = tuple(key for key, _title in PROPERTY_FORM_SECTIONS)
_NARRATION = "표시된 판정이 무엇을 뜻하는지 설명하는 문장입니다."


class _FakeClient:
    """작성 요청이면 절별 서술을, 판정 요청이면 전부 OK를 돌려준다."""

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
            payload: dict[str, Any] = {
                key: {"verdict": "OK", "reason": ""} for key in _KEYS
            }
            return GenerationResult(text=json.dumps(payload, ensure_ascii=False), model="j")
        return GenerationResult(
            text=json.dumps({key: _NARRATION for key in _KEYS}, ensure_ascii=False),
            model="w",
        )


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.reports.ai_explanation.form_agent.GeminiClient", _FakeClient
    )
    monkeypatch.setattr(
        "app.reports.ai_explanation.verifier_agent.GeminiClient", _FakeClient
    )


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


def test_property_report_returns_the_calculation_and_the_narrated_form(
    fake_ai: None,
) -> None:
    response = TestClient(app).post("/api/v1/reports/property", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["fully_verified"] is True
    assert set(body["adopted_sections"]) == set(_KEYS)
    assert body["figures_only_sections"] == []
    # 보고서와 함께 산출 근거가 되는 계산 결과가 그대로 돌아온다.
    assert body["affordability"]["total_count"] == 1
    assert body["affordability"]["assessments"][0]["verdict"] == "AFFORDABLE"
    assert body["search_snapshot_id"] == body["affordability"]["search_result"][
        "search_snapshot_id"
    ]
    assert "매물별 구매 가능성 보고서" in body["markdown"]


def test_property_report_never_echoes_the_request_profile(fake_ai: None) -> None:
    response = TestClient(app).post("/api/v1/reports/property", json=_payload())

    assert "PRIVATE-PERSONA" not in response.json()["markdown"]


def test_property_report_print_format_is_a_complete_document(fake_ai: None) -> None:
    response = TestClient(app).post(
        "/api/v1/reports/property?format=print",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert html.startswith("<!doctype html>")
    # 저장한 파일을 열어 인쇄하는 것이 정상 사용법이라 문서 자체에 charset이 있어야 한다.
    assert "<meta charset='utf-8'>" in html
    assert "매물별 산출 결과 총괄" in html
    assert "대출 승인 통지도" in html


def test_property_report_survives_without_an_ai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI가 없어도 수치는 나온다 — 고정 템플릿 fallback."""

    class _Unconfigured(_FakeClient):
        def generate(self, **_kwargs: Any) -> GenerationResult:
            return GenerationResult(
                text=None, model="m", error="GEMINI_API_KEY가 설정되지 않았습니다."
            )

    monkeypatch.setattr(
        "app.reports.ai_explanation.form_agent.GeminiClient", _Unconfigured
    )
    monkeypatch.setattr(
        "app.reports.ai_explanation.verifier_agent.GeminiClient", _Unconfigured
    )

    response = TestClient(app).post("/api/v1/reports/property", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["fully_verified"] is False
    assert body["adopted_sections"] == []
    assert set(body["figures_only_sections"]) == set(_KEYS)
    assert "검색 조건과 데이터 기준시점" in body["markdown"]


def test_property_report_rejects_a_per_listing_amount_override(fake_ai: None) -> None:
    payload = _payload()
    payload["loan_request"] = {
        "months": 360,
        "housing_status": "FIRST_HOME_BUYER",
        "monthly_essential_expense": "2000000",
        "required_amount": "10000000",
    }

    response = TestClient(app).post("/api/v1/reports/property", json=payload)

    assert response.status_code == 422
    assert "calculated per listing" in str(response.json()["detail"])
