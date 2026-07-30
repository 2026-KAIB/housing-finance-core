"""보고서 설명 에이전트가 계산 결과 밖으로 나가지 않는지 검증한다.

네트워크를 쓰지 않는다. 생성기는 ``ExplanationClient`` 프로토콜을 만족하는 가짜를
넣어 "AI가 이렇게 답했다면 어떻게 되는가"만 확인한다. 실제 Gemini 호출을 테스트에
넣으면 CI가 외부 서비스와 키에 의존하게 되고, 무엇보다 계산 결과가 매번 외부로
전송된다.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.core.config import Settings
from app.regulations.mortgage_limits import HousingStatus
from app.reports.ai_explanation.agent import build_user_prompt, explain_report
from app.reports.ai_explanation.egress import scan_payload
from app.reports.ai_explanation.gemini import GenerationResult, _first_candidate
from app.reports.context import build_report_ai_input
from app.reports.templates.basic import build_template_report
from app.reports.validation.numbers import _ISO_DATE, _extract_numbers, verify_explanation
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule
from app.schemas.report import ReportAIInput
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SimulationInput,
    UserProfile,
)
from app.services.simulation_orchestrator import run_simulation

_AS_OF = date(2026, 7, 28)
_CALCULATED_AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
_SIMULATION_ID = UUID("0f9b21e4-4c1a-4d7f-9c3e-2b6a5d8e1f30")
_MORTGAGE = "KB 주택담보대출"


@dataclass
class FakeClient:
    """정해진 답만 돌려주는 생성기. 호출 여부도 기록한다."""

    result: GenerationResult
    calls: list[tuple[str, str]] = field(default_factory=list)

    def generate(self, *, system_prompt: str, user_prompt: str) -> GenerationResult:
        self.calls.append((system_prompt, user_prompt))
        return self.result


def _settings(**overrides: object) -> Settings:
    # `.env`를 읽지 않도록 값을 명시한다. 개발자 로컬 키가 테스트에 새어들면
    # 테스트 결과가 환경에 따라 달라진다.
    base: dict[str, object] = {
        "gemini_api_key": None,
        "report_ai_egress_guard": True,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def report_input() -> ReportAIInput:
    """실제 파이프라인을 거친 보고서 입력."""
    payload = SimulationInput(
        profile=UserProfile(age=34, annual_income=Decimal("60000000"), is_first_home_buyer=True),
        housing_goal=HousingGoal(
            target_amount=Decimal("500000000"),
            target_date=date(2028, 7, 30),
            region_code="11680",
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            liquid_assets=Decimal("150000000"),
            monthly_debt_payment=Decimal("300000"),
        ),
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal("1800000"),
        ),
    )
    pack = ProductRulePack(
        product_name=_MORTGAGE,
        category=ProductCategory.MORTGAGE_LOAN,
        version="test-1",
        effective_start_date=date(2026, 1, 1),
        effective_end_date=None,
        rules=(
            ComparisonRule(
                code="TEST_MIN_AGE",
                field_name="age",
                operator=ComparisonOperator.GTE,
                expected=19,
                failure_reason="미성년자는 신청할 수 없습니다.",
            ),
        ),
    )
    candidate = ProductCandidate(
        product_name=_MORTGAGE,
        base_data={
            "source_type": "manual_pdf",
            "fin_prdt_nm": _MORTGAGE,
            "loan_lmt": "담보조사가격 및 소득금액에 따른 대출가능금액 이내",
        },
        option_list=(
            {
                "fin_prdt_nm": _MORTGAGE,
                "mrtg_type_nm": "아파트",
                "rpay_type_nm": "분할상환방식",
                "lend_rate_type_nm": "변동금리",
                "lend_rate_min": 3.0,
                "lend_rate_max": 3.0,
                "lend_rate_avg": 3.0,
            },
        ),
    )
    result = run_simulation(
        payload,
        simulation_id=_SIMULATION_ID,
        as_of=_AS_OF,
        calculated_at=_CALCULATED_AT,
        loan_candidates=[candidate],
        registry=ProductRulePackRegistry((pack,)),
    )
    return build_report_ai_input(result)


class TestTemplateReport:
    def test_not_run_sections_say_so_instead_of_showing_zero(
        self,
        report_input: ReportAIInput,
    ) -> None:
        text = build_template_report(report_input).to_text()

        assert "현금흐름 진단" in text
        # 실행하지 않은 구간을 "0원"이나 "불가"로 단정하지 않고 그대로 말한다.
        assert "아직 계산하지 않았습니다" in text
        assert "불가" not in text

    def test_report_carries_sources_and_disclaimers(
        self,
        report_input: ReportAIInput,
    ) -> None:
        text = build_template_report(report_input).to_text()

        assert "근거 출처" in text
        assert "보장하지 않습니다" in text


class TestVerifier:
    def test_an_invented_amount_is_a_violation(self, report_input: ReportAIInput) -> None:
        result = verify_explanation("최대 999,999,999원까지 받을 수 있습니다.", report_input)

        assert not result.ok
        assert any(item.value == "999,999,999" for item in result.violations)

    def test_an_unknown_product_is_a_violation(self, report_input: ReportAIInput) -> None:
        result = verify_explanation("신한 전세안심대출을 추천합니다.", report_input)

        assert not result.ok
        assert any(item.kind == "product_name" for item in result.violations)

    def test_a_date_outside_the_result_is_a_violation(
        self,
        report_input: ReportAIInput,
    ) -> None:
        result = verify_explanation("2030-01-01까지 준비하십시오.", report_input)

        assert not result.ok
        assert any(item.kind == "date" for item in result.violations)

    def test_text_that_only_repeats_the_result_passes(
        self,
        report_input: ReportAIInput,
    ) -> None:
        goal = f"{int(report_input.goal.target_amount):,}원"
        result = verify_explanation(
            f"목표 금액은 {goal}이고 기준일은 {report_input.as_of.isoformat()}입니다.",
            report_input,
        )

        assert result.ok, result.violations

    def test_amounts_quoted_from_reason_sentences_are_allowed(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """엔진의 ``reasons`` 문장에 박힌 금액을 인용하는 것은 위반이 아니다.

        ``reasons``는 문자열 리스트다. 리스트 원소를 순회하지 않으면 그 안의 금액을
        전부 놓쳐, AI가 근거를 정확히 인용해도 "지어낸 수"로 잡힌다. 실제로 그랬다.
        """
        reasons = [
            reason
            for section in (report_input.sections.loan, report_input.sections.recommendation)
            for reason in section.reasons
        ]
        quoted = [
            number
            for reason in reasons
            for number in _extract_numbers(reason)
        ]
        assert quoted, "근거 문장에 서식화된 금액이 있어야 이 테스트가 의미를 가진다"

        result = verify_explanation(f"근거에 따르면 {quoted[0]}원이 부족합니다.", report_input)

        assert result.ok, result.violations

    def test_policy_dates_inside_source_strings_are_allowed(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """``policy_sources`` 문장 속 시행일 인용도 허용된다."""
        dates = [
            match
            for source in report_input.policy_sources
            for match in _ISO_DATE.findall(source)
        ]
        assert dates, "출처 문장에 시행일이 있어야 이 테스트가 의미를 가진다"

        result = verify_explanation(f"{dates[0]} 시행 규제를 적용했습니다.", report_input)

        assert result.ok, result.violations

    def test_prose_integers_are_not_flagged(self, report_input: ReportAIInput) -> None:
        """"세 가지"처럼 단위 없는 작은 수는 검사 대상이 아니다."""
        result = verify_explanation("확인할 항목이 3개 있습니다.", report_input)

        assert result.ok, result.violations


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

    def test_large_amounts_are_not_mistaken_for_account_numbers(self) -> None:
        """금액 필드의 큰 정수는 계좌번호가 아니다. 여기서 막히면 기능이 죽는다."""
        report = scan_payload(
            {"sections": {"loan": {"facts": {"amount": "283520507", "annual_income": "60000000"}}}}
        )

        assert report.allowed, report.findings

    def test_a_clean_report_input_passes(self, report_input: ReportAIInput) -> None:
        report = scan_payload(report_input.to_json_dict())

        assert report.allowed, report.findings


class TestGeminiResponseHandling:
    """응답 파싱은 네트워크 없이 순수 함수로 검증한다."""

    def test_a_truncated_response_is_treated_as_failure(self) -> None:
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


class TestAgent:
    def test_missing_api_key_still_returns_the_template_report(
        self,
        report_input: ReportAIInput,
    ) -> None:
        result = explain_report(report_input, settings=_settings())

        assert result.adopted is False
        assert "GEMINI_API_KEY" in " ".join(result.notes)
        # 핵심: 계산 결과는 그대로 나온다.
        assert "주택자금 계획 보고서" in result.to_text()

    def test_verified_explanation_is_appended(self, report_input: ReportAIInput) -> None:
        goal = f"{int(report_input.goal.target_amount):,}원"
        client = FakeClient(
            GenerationResult(text=f"## 요약\n목표는 {goal}입니다.", model="fake")
        )

        result = explain_report(report_input, client=client, settings=_settings())

        assert result.adopted is True
        assert "## 요약" in result.to_text()

    def test_explanation_with_an_invented_number_is_not_adopted(
        self,
        report_input: ReportAIInput,
    ) -> None:
        client = FakeClient(
            GenerationResult(text="## 요약\n최대 987,654,321원까지 가능합니다.", model="fake")
        )

        result = explain_report(report_input, client=client, settings=_settings())

        assert result.adopted is False
        assert result.explanation is not None  # 무엇이 거부됐는지 남긴다
        assert "987,654,321" not in result.to_text()
        assert result.verification is not None and not result.verification.ok

    def test_blocked_egress_never_calls_the_model(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """전송이 막히면 호출 자체가 없어야 한다. 나간 뒤에는 되돌릴 수 없다."""
        tainted = _TaintedInput.model_validate(report_input.model_dump())
        client = FakeClient(GenerationResult(text="## 요약\n무해한 문장", model="fake"))

        result = explain_report(tainted, client=client, settings=_settings())

        assert client.calls == []
        assert result.adopted is False
        assert result.egress is not None and not result.egress.allowed

    def test_prompt_carries_the_generation_rules(self, report_input: ReportAIInput) -> None:
        prompt = build_user_prompt(report_input)

        assert "생성 규칙" in prompt
        for rule in report_input.generation_rules:
            assert rule in prompt


class _TaintedInput(ReportAIInput):
    """전송 페이로드에만 개인정보가 섞인 입력.

    실제 ``ReportAIInput``은 ``extra="forbid"``라 계좌번호 필드를 만들 수 없다.
    게이트가 **스키마가 아니라 값의 모양**으로 판단하는지 보려면 직렬화 결과만
    오염시켜야 한다. 나머지는 정상 입력이라 템플릿 보고서는 그대로 만들어진다.
    """

    def to_json_dict(self) -> dict[str, object]:
        payload = super().to_json_dict()
        payload["sections"]["financial_diagnosis"]["facts"] = {"memo": "901201-1234567"}
        return payload
