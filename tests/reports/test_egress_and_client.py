"""외부 전송 게이트와 Gemini 응답 처리.

둘 다 네트워크를 쓰지 않는다 — 게이트는 순수 함수이고, 응답 처리는 저장된 응답
모양으로만 검증한다. 실제 호출을 테스트에 넣으면 CI가 외부 서비스에 의존하고
계산 결과가 매번 외부로 전송된다.
"""

import pytest

from app.reports.ai_explanation.egress import scan_payload
from app.reports.ai_explanation.gemini import _first_candidate
from app.reports.validation.numbers import collect_source_names
from app.schemas.report import ReportAIInput
from tests.reports.conftest import MORTGAGE_PRODUCT


class TestEgressGuard:
    @pytest.mark.parametrize(
        ("value", "kind"),
        [
            ("901201-1234567", "resident_registration_number"),
            ("110-234-567890", "account_number"),
            ("010-1234-5678", "phone_number"),
            ("hong@example.com", "email"),
            ("AIzaSyAbcdefghijklmnopqrstuvwxyz12345", "credential"),
        ],
    )
    def test_identifier_shapes_are_found(self, value: str, kind: str) -> None:
        report = scan_payload({"sections": {"financial_diagnosis": {"note": value}}})

        assert not report.allowed
        assert report.findings[0].kind == kind

    def test_a_phone_number_is_not_reported_as_an_account_number(self) -> None:
        """휴대전화번호는 계좌번호 형태에도 들어맞는다. 더 구체적인 판정이 이겨야 한다."""
        report = scan_payload({"memo": "010-1234-5678"})

        assert report.findings[0].kind == "phone_number"

    def test_large_amounts_are_not_mistaken_for_account_numbers(self) -> None:
        """금액 필드의 큰 정수는 계좌번호가 아니다. 여기서 막히면 기능이 죽는다."""
        report = scan_payload(
            {"sections": {"loan": {"facts": {"amount": "283520507", "annual_income": "60000000"}}}}
        )

        assert report.allowed, report.findings

    def test_dates_are_not_mistaken_for_account_numbers(self) -> None:
        """`2026-07-28`은 계좌번호 형태와 겹친다.

        걸러내지 않으면 기준일·시행일이 모두 계좌번호로 오인돼 **정상 트래픽이 전부
        차단된다.** 실제로 그렇게 됐다.
        """
        report = scan_payload(
            {
                "as_of": "2026-07-28",
                "policy_sources": ["「가계부채 관리 강화 방안」(2025-06-27, 시행 2025-06-28)"],
            }
        )

        assert report.allowed, report.findings

    def test_a_clean_report_input_passes(self, report_input: ReportAIInput) -> None:
        report = scan_payload(report_input.to_json_dict())

        assert report.allowed, report.findings


class TestGeminiResponseHandling:
    def test_a_truncated_response_is_reported_with_its_finish_reason(self) -> None:
        """잘린 본문을 성공으로 보면 숫자가 중간에서 끊긴 보고서가 나간다.

        검증기는 "지어낸 수"를 잡지만 "350,00"처럼 **끊긴 수**는 패턴에 맞지 않아
        통과한다. 그래서 종료 사유로 걸러야 한다. 실제로 겪은 증상이다.
        """
        text, reason = _first_candidate(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "목표는 350,00"}]},
                        "finishReason": "MAX_TOKENS",
                    }
                ]
            }
        )

        assert text == "목표는 350,00"
        assert reason == "MAX_TOKENS"

    def test_a_normal_response_reports_stop(self) -> None:
        text, reason = _first_candidate(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "## 요약"}]}, "finishReason": "STOP"}
                ]
            }
        )

        assert text == "## 요약"
        assert reason == "STOP"

    def test_an_empty_candidate_list_yields_nothing(self) -> None:
        assert _first_candidate({"candidates": []}) == (None, None)

    def test_a_non_dict_payload_yields_nothing(self) -> None:
        assert _first_candidate("not json") == (None, None)


class TestSourceNames:
    def test_product_names_inside_list_elements_are_collected(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """리스트 원소를 순회하지 않으면 상품명을 전부 놓친다.

        상품 기록은 ``executable``·``rejected`` 같은 **리스트 안의 dict**에 있다.
        예전에 리스트 원소를 내보내지 않아 실제로 놓쳤던 자리다.
        """
        names = collect_source_names(report_input)

        assert MORTGAGE_PRODUCT in names
