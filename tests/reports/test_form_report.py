"""고정 양식 보고서: 수치는 엔진이, 문장은 AI가.

자유 서술판에서는 값은 맞고 귀속만 틀린 문장이 검증을 통과했다("목표 금액 대비
66,479,492원 부족", 실은 필요 대출금액 대비). 고정 양식은 서술 칸에서 수치를 아예
금지해 그 오류를 구조적으로 불가능하게 만든다 — 그 불변식을 여기서 고정한다.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.core.config import Settings
from app.regulations.mortgage_limits import HousingStatus
from app.reports.ai_explanation.form_agent import (
    FORM_SECTIONS,
    build_form_prompt,
    explain_report_form,
    narration_response_schema,
)
from app.reports.ai_explanation.gemini import GenerationResult
from app.reports.context import build_report_ai_input
from app.reports.templates.form import build_report_form
from app.reports.validation.numbers import verify_narration
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
_MORTGAGE = "KB 주택담보대출"
_SECTION_KEYS = tuple(key for key, _title in FORM_SECTIONS)


@dataclass
class FakeClient:
    result: GenerationResult
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> GenerationResult:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_schema": response_schema,
            }
        )
        return self.result


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None).model_copy(
        update={"gemini_api_key": None, "report_ai_egress_guard": True, **overrides}
    )


def _narration_payload(text: str) -> str:
    return json.dumps({key: text for key in _SECTION_KEYS}, ensure_ascii=False)


@pytest.fixture(scope="module")
def report_input() -> ReportAIInput:
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
        simulation_id=UUID("0f9b21e4-4c1a-4d7f-9c3e-2b6a5d8e1f30"),
        as_of=_AS_OF,
        calculated_at=datetime(2026, 7, 28, 9, 0, tzinfo=UTC),
        loan_candidates=[candidate],
        registry=ProductRulePackRegistry((pack,)),
    )
    return build_report_ai_input(result)


class TestForm:
    def test_all_six_ssot_sections_are_present_in_order(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """SSOT §19의 여섯 항목이 순서 그대로 나온다."""
        form = build_report_form(report_input)

        assert tuple(item.key for item in form.sections) == _SECTION_KEYS
        text = form.to_text()
        positions = [text.index(item.title) for item in form.sections]
        assert positions == sorted(positions)

    def test_amounts_are_rendered_as_whole_won(self, report_input: ReportAIInput) -> None:
        """이분탐색 소수점을 사용자에게 보이지 않는다."""
        text = build_report_form(report_input).to_text()

        assert "283,520,507원" in text
        assert "283520507.8125" not in text
        assert ".8125" not in text

    def test_the_shortfall_states_its_basis(self, report_input: ReportAIInput) -> None:
        """부족액이 무엇 대비인지 양식이 직접 밝힌다.

        AI가 "목표 금액 대비"로 잘못 귀속했던 자리다. 기준을 엔진이 박아 두면
        그 오류가 생길 자리가 없어진다.
        """
        text = build_report_form(report_input).to_text()

        assert "**필요 대출금액 대비** 부족액" in text
        assert "목표 금액 대비" not in text

    def test_both_rates_are_shown_and_labelled(self, report_input: ReportAIInput) -> None:
        """실제 금리와 심사용 금리를 나란히 두고 후자가 실제 금액이 아님을 밝힌다."""
        text = build_report_form(report_input).to_text()

        assert "실제 적용 금리" in text
        assert "심사용 금리" in text
        assert "실제로 내는 금리가 아닙니다" in text

    def test_raw_enum_and_field_names_get_korean_labels(
        self,
        report_input: ReportAIInput,
    ) -> None:
        text = build_report_form(report_input).to_text()

        assert "주택 구입" in text
        assert "HOME_PURCHASE" not in text
        # 원래 이름은 괄호로 남긴다 — 결측을 숨기지 않는다.
        assert "대출 부대비용" in text
        assert "(total_cost)" in text

    def test_uncalculated_sections_say_what_is_needed(
        self,
        report_input: ReportAIInput,
    ) -> None:
        text = build_report_form(report_input).to_text()

        assert "자산축적형 전략 비교가 계산된 뒤에 산출됩니다" in text


class TestNarrationVerifier:
    def test_any_amount_in_a_narration_slot_is_a_violation(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """값이 실제로 맞아도 서술 칸에서는 위반이다. 이게 자유 서술판과의 차이다."""
        result = verify_narration("대출 가능액은 283,520,507원입니다.", report_input)

        assert not result.ok
        assert result.violations[0].kind == "number_in_narration"

    def test_a_date_in_a_narration_slot_is_a_violation(
        self,
        report_input: ReportAIInput,
    ) -> None:
        result = verify_narration("2026-07-28 기준입니다.", report_input)

        assert not result.ok
        assert any(item.kind == "date_in_narration" for item in result.violations)

    def test_prose_without_figures_passes(self, report_input: ReportAIInput) -> None:
        result = verify_narration(
            "표시된 대출 가능액은 필요 대출금액에 미치지 못합니다. "
            "부족한 만큼은 자기자본으로 메워야 합니다.",
            report_input,
        )

        assert result.ok, result.violations

    def test_an_unknown_product_is_still_a_violation(
        self,
        report_input: ReportAIInput,
    ) -> None:
        result = verify_narration("신한 전세안심대출도 함께 검토하십시오.", report_input)

        assert not result.ok
        assert any(item.kind == "product_name" for item in result.violations)


class TestFormAgent:
    def test_structured_schema_asks_for_every_section(self) -> None:
        schema = narration_response_schema()

        assert set(schema["properties"]) == set(_SECTION_KEYS)
        assert schema["required"] == list(_SECTION_KEYS)

    def test_prompt_shows_rendered_figures_not_raw_json(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """양식에 렌더링된 수치만 보여준다. 원본 JSON을 다 주면 다른 수치를 끌어온다."""
        form = build_report_form(report_input)
        prompt = build_form_prompt(report_input, form)

        assert "283,520,507원" in prompt
        assert "simulation_id" not in prompt

    def test_clean_narrations_fill_every_slot(self, report_input: ReportAIInput) -> None:
        client = FakeClient(
            GenerationResult(
                text=_narration_payload("표시된 결과의 의미를 설명하는 문장입니다."),
                model="fake",
            )
        )

        report = explain_report_form(report_input, client=client, settings=_settings())

        assert report.fully_narrated
        assert report.rejected_sections == ()
        assert client.calls[0]["response_schema"] is not None

    def test_a_slot_with_a_number_is_dropped_but_the_rest_survive(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """한 칸이 틀려서 보고서 전체를 버리지 않는다."""
        rejected_sentence = "최악 시나리오 DSR은 45.55%입니다."
        payload = json.loads(_narration_payload("깨끗한 설명 문장입니다."))
        payload["base_vs_stress"] = rejected_sentence
        client = FakeClient(GenerationResult(text=json.dumps(payload), model="fake"))

        report = explain_report_form(report_input, client=client, settings=_settings())
        text = report.to_text()

        assert report.rejected_sections == ("base_vs_stress",)
        assert len(report.adopted_sections) == len(_SECTION_KEYS) - 1
        # 거부된 서술은 사라지고,
        assert rejected_sentence not in text
        # 엔진이 렌더링한 같은 수치는 그대로 남는다 — 사용자가 값을 잃지 않는다.
        assert "최악 시나리오 예상 DSR: 45.55%" in text
        assert "깨끗한 설명 문장입니다." in text

    def test_invalid_json_leaves_the_form_intact(self, report_input: ReportAIInput) -> None:
        client = FakeClient(GenerationResult(text="이건 JSON이 아닙니다", model="fake"))

        report = explain_report_form(report_input, client=client, settings=_settings())

        assert report.adopted_sections == ()
        assert any("JSON" in note for note in report.notes)
        # 수치 보고서는 그대로 제공된다.
        assert "283,520,507원" in report.to_text()

    def test_missing_api_key_still_returns_the_figures(
        self,
        report_input: ReportAIInput,
    ) -> None:
        report = explain_report_form(report_input, settings=_settings())

        assert report.adopted_sections == ()
        assert "283,520,507원" in report.to_text()
