"""매물별 보고서: 계약 → 양식 → 기계 검증 → 두 에이전트.

고정하는 불변식:
1. 보고서 입력에 요청 원본(페르소나·재무 스냅샷)이 들어가지 않는다.
2. 판정 불가를 구매 불가로 바꾸지 않는다(§22.1).
3. 서술 칸이 **매물을 특정할 수 없다** — 매물별 결과가 섞일 수 없게 만든다.
4. 기계 검증이 하드 게이트이며, 막혀도 수치는 남는다.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.core.config import Settings
from app.engines.affordability import AffordabilityVerdict
from app.reports.ai_explanation.gemini import GenerationResult
from app.reports.ai_explanation.pipeline import build_report_from_spec
from app.reports.ai_explanation.property_agent import property_narration_spec
from app.reports.property_context import build_property_report_ai_input
from app.reports.templates.property_form import (
    PROPERTY_FORM_SECTIONS,
    build_property_report_form,
)
from app.reports.templates.property_official import render_property_official_report
from app.reports.validation.property_narration import verify_property_narration
from app.repositories import JsonPropertyListingRepository
from app.schemas.property import PropertySearchCriteria, PropertyType
from app.schemas.property_affordability import (
    PropertyAcquisitionFactsInput,
    PropertyAcquisitionProfileInput,
    PropertyAffordabilitySearchRequest,
)
from app.schemas.property_report import PropertyReportAIInput
from app.schemas.simulation import (
    FinancialSnapshot,
    LoanRequestInput,
    SectionRunStatus,
    UserProfile,
)
from app.services.cashflow_diagnosis import diagnose_financial_snapshot
from app.services.property_affordability_api import (
    evaluate_property_search_affordability,
)

SEOUL = ZoneInfo("Asia/Seoul")
CALCULATED_AT = datetime(2026, 7, 30, 10, tzinfo=SEOUL)
DATASET = (
    Path(__file__).resolve().parents[2]
    / "sample_data"
    / "property_listings"
    / "property_listings.v1.json"
)
_KEYS = tuple(key for key, _title in PROPERTY_FORM_SECTIONS)
_CLEAN = "표시된 판정이 무엇을 뜻하는지 설명하는 문장입니다."


def _request(
    *,
    liquid_assets: Decimal = Decimal("100000000"),
    property_types: tuple[PropertyType, ...] = (),
    acquisition_profile: PropertyAcquisitionProfileInput | None = None,
    loan_request: LoanRequestInput | None = None,
) -> PropertyAffordabilitySearchRequest:
    return PropertyAffordabilitySearchRequest(
        criteria=PropertySearchCriteria(
            region_codes=("11620",),
            property_types=property_types,
        ),
        profile=UserProfile(
            persona_name="PRIVATE-PERSONA",
            age=30,
            annual_income=Decimal("60000000"),
            is_first_home_buyer=True,
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            monthly_debt_payment=Decimal(0),
            liquid_assets=liquid_assets,
            emergency_reserve=Decimal("6000000"),
        ),
        loan_request=loan_request,
        acquisition_profile=acquisition_profile
        or PropertyAcquisitionProfileInput(
            buyer_is_corporation=False,
            household_home_count_after_purchase=1,
            default_property_facts=PropertyAcquisitionFactsInput(
                is_registered_housing=True,
                is_luxury_home=False,
                registration_and_legal_costs=Decimal("186000"),
            ),
        ),
    )


def _build_input(payload: PropertyAffordabilitySearchRequest) -> PropertyReportAIInput:
    response = evaluate_property_search_affordability(
        payload,
        JsonPropertyListingRepository(DATASET),
        calculated_at=CALCULATED_AT,
        id_factory=lambda: UUID("00000000-0000-0000-0000-000000000009"),
    )
    return build_property_report_ai_input(
        response,
        as_of=CALCULATED_AT.date(),
        cashflow_result=diagnose_financial_snapshot(
            payload.financial_snapshot,
            as_of=CALCULATED_AT.date(),
        ),
    )


@pytest.fixture(scope="module")
def report_input() -> PropertyReportAIInput:
    """관악구 전 매물. 판정이 한 종류로 몰리지 않아 절별 서술을 다 볼 수 있다."""
    return _build_input(_request())


@pytest.fixture(scope="module")
def unknown_input() -> PropertyReportAIInput:
    """취득 사실을 주지 않아 전 매물이 판정 불가인 경우."""
    return _build_input(
        _request(acquisition_profile=PropertyAcquisitionProfileInput())
    )


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
        self.calls.append({"user_prompt": user_prompt, "response_schema": response_schema})
        return self.result


def _settings() -> Settings:
    return Settings(_env_file=None).model_copy(
        update={"gemini_api_key": None, "report_ai_egress_guard": True}
    )


def _writer(text: str = _CLEAN, **overrides: str) -> FakeClient:
    payload = {key: text for key in _KEYS}
    payload.update(overrides)
    return FakeClient(GenerationResult(text=json.dumps(payload, ensure_ascii=False), model="w"))


def _judge(default: str = "OK", **overrides: str) -> FakeClient:
    payload = {key: {"verdict": default, "reason": ""} for key in _KEYS}
    for key, verdict in overrides.items():
        payload[key] = {"verdict": verdict, "reason": f"{key} 지적 사유"}
    return FakeClient(GenerationResult(text=json.dumps(payload, ensure_ascii=False), model="j"))


# --------------------------------------------------------------------------
# 계약
# --------------------------------------------------------------------------


def test_report_input_excludes_request_profile_and_snapshot(
    report_input: PropertyReportAIInput,
) -> None:
    encoded = report_input.model_dump_json()

    assert "PRIVATE-PERSONA" not in encoded
    assert "persona_name" not in encoded
    assert "financial_snapshot" not in encoded
    # 검색 조건은 개인 식별 정보가 아니고 절 1이 필요로 한다.
    assert report_input.criteria.region_codes == ("11620",)
    assert report_input.handoff.items


def test_report_input_carries_the_cashflow_diagnosis(
    report_input: PropertyReportAIInput,
) -> None:
    diagnosis = report_input.financial_diagnosis

    assert diagnosis.run_status is SectionRunStatus.COMPLETED
    assert diagnosis.facts is not None
    assert "diagnosis" in diagnosis.facts
    assert diagnosis.reasons


def test_missing_inputs_merge_handoff_and_diagnosis_without_duplicates(
    unknown_input: PropertyReportAIInput,
) -> None:
    merged = unknown_input.missing_inputs

    assert "buyer_is_corporation" in merged
    assert len(merged) == len(set(merged))


# --------------------------------------------------------------------------
# 양식
# --------------------------------------------------------------------------


def test_every_section_renders_figures(report_input: PropertyReportAIInput) -> None:
    form = build_property_report_form(report_input)

    assert tuple(section.key for section in form.sections) == _KEYS
    assert all(section.figures for section in form.sections)
    assert all(section.narration is None for section in form.sections)


def test_unknown_verdict_is_not_rendered_as_impossible(
    unknown_input: PropertyReportAIInput,
) -> None:
    form = build_property_report_form(unknown_input)
    verdicts = form.section("affordability_verdicts")
    summary = form.section("comparison_summary")

    assert verdicts is not None and summary is not None
    text = "\n".join(verdicts.figures + summary.figures)
    assert "판정 불가(입력 부족)" in text
    assert "구매 불가" not in text
    assert any("구매할 수 없다는 뜻이 아니라" in line for line in verdicts.figures)


def test_unconfirmed_total_cost_does_not_borrow_the_minimum(
    unknown_input: PropertyReportAIInput,
) -> None:
    """총액을 확정하지 못했을 때 최소액을 총액 자리에 넣지 않는다."""
    section = build_property_report_form(unknown_input).section("purchase_costs")

    assert section is not None
    joined = "\n".join(section.figures)
    assert "총구매비용 확인되지 않음" in joined
    assert "확인된 최소" in joined


def test_listing_lines_are_capped_and_say_how_many_were_left_out(
    report_input: PropertyReportAIInput,
) -> None:
    """조용히 자르지 않는다 — 자른 건수를 문서가 밝힌다."""
    many = report_input.model_copy(
        update={
            "handoff": report_input.handoff.model_copy(
                update={"items": report_input.handoff.items * 5}
            )
        }
    )
    section = build_property_report_form(many).section("purchase_costs")

    assert section is not None
    listing_lines = [line for line in section.figures if line.startswith("- 매물 ")]
    assert len(listing_lines) == 10
    assert any("나머지" in line and "건" in line for line in section.figures)


def test_a_cash_purchase_is_not_rendered_as_an_unknown_payment(
    report_input: PropertyReportAIInput,
) -> None:
    """필요 대출이 0으로 산출된 매물은 "확인되지 않음"이 아니라 "없음"이다.

    모름을 0으로 뭉개지 않는 것과 같은 이유로, 확인된 0을 모름으로 뭉개서도 안 된다.
    """
    cash = [
        item
        for item in report_input.handoff.items
        if item.required_loan_amount == Decimal(0)
    ]
    assert cash, "이 픽스처에는 자기자금 구매 매물이 있어야 한다"

    form = build_property_report_form(report_input)
    funding = form.section("loan_funding")
    burden = form.section("monthly_burden")
    stress = form.section("stress_result")
    assert funding is not None and burden is not None and stress is not None

    # 자기자금 구매 매물의 수만큼만 바뀐다. 필요 대출금액을 **산출하지 못한**
    # 매물은 그대로 "확인되지 않음"으로 남아야 한다 — 그쪽은 진짜 모름이다.
    assert sum("필요 대출 없음" in line for line in funding.figures) == len(cash)
    assert sum("월 상환액 없음(대출 미사용)" in line for line in burden.figures) == len(cash)
    assert sum("스트레스가 적용되지 않습니다" in line for line in stress.figures) == len(cash)

    unresolved = [
        item for item in report_input.handoff.items if item.required_loan_amount is None
    ]
    assert sum("월 상환액 확인되지 않음" in line for line in burden.figures) == len(
        unresolved
    )


def test_form_carries_property_specific_disclaimers(
    report_input: PropertyReportAIInput,
) -> None:
    form = build_property_report_form(report_input)

    assert any("매물 정보는" in item for item in form.disclaimers)
    assert any("대출 승인" in item for item in form.disclaimers)


# --------------------------------------------------------------------------
# 기계 검증
# --------------------------------------------------------------------------


def test_clean_narration_passes(report_input: PropertyReportAIInput) -> None:
    result = verify_property_narration(_CLEAN, report_input, section_key="purchase_costs")

    assert result.ok
    assert result.violations == ()


def test_narration_cannot_name_a_listing(report_input: PropertyReportAIInput) -> None:
    name = report_input.handoff.items[0].property_name
    assert name is not None

    result = verify_property_narration(
        f"{name}은 표시된 금액으로 구매를 검토할 수 있습니다.",
        report_input,
        section_key="affordability_verdicts",
    )

    assert not result.ok
    assert any(item.kind == "listing_reference" for item in result.violations)


def test_narration_cannot_point_at_a_listing_by_number(
    report_input: PropertyReportAIInput,
) -> None:
    result = verify_property_narration(
        "매물 1은 여유가 있고 나머지는 그렇지 않습니다.",
        report_input,
        section_key="comparison_summary",
    )

    assert not result.ok
    assert any(item.value == "매물 1" for item in result.violations)


def test_narration_cannot_contain_numbers(report_input: PropertyReportAIInput) -> None:
    result = verify_property_narration(
        "총구매비용은 1,234,000원입니다.",
        report_input,
        section_key="purchase_costs",
    )

    assert not result.ok
    assert any(item.kind == "number_in_narration" for item in result.violations)


def test_narration_cannot_claim_approval(report_input: PropertyReportAIInput) -> None:
    result = verify_property_narration(
        "표시된 조건이면 대출이 승인됩니다.",
        report_input,
        section_key="loan_funding",
    )

    assert not result.ok
    assert any(item.kind == "guarantee" for item in result.violations)


def test_narration_cannot_mention_an_unlisted_loan_product(
    report_input: PropertyReportAIInput,
) -> None:
    result = verify_property_narration(
        "카카오뱅크 주택담보대출을 함께 검토하십시오.",
        report_input,
        section_key="loan_funding",
    )

    assert not result.ok
    assert any(item.kind == "product_name" for item in result.violations)


def test_affordability_claim_is_blocked_when_nothing_is_affordable(
    unknown_input: PropertyReportAIInput,
) -> None:
    assert all(
        item.verdict is AffordabilityVerdict.UNKNOWN
        for item in unknown_input.handoff.items
    )

    result = verify_property_narration(
        "표시된 조건에서는 구매할 수 있습니다.",
        unknown_input,
        section_key="affordability_verdicts",
    )

    assert not result.ok
    assert any(item.kind == "verdict_overreach" for item in result.violations)


def test_impossibility_claim_is_blocked_when_everything_is_unresolved(
    unknown_input: PropertyReportAIInput,
) -> None:
    """판정 불가는 구매 불가가 아니다 — 반대 방향으로도 단정하지 못하게 막는다."""
    result = verify_property_narration(
        "표시된 조건에서는 구매할 수 없습니다.",
        unknown_input,
        section_key="affordability_verdicts",
    )

    assert not result.ok
    assert any(item.kind == "verdict_overreach" for item in result.violations)


def test_resolved_claim_is_blocked_while_inputs_are_missing(
    unknown_input: PropertyReportAIInput,
) -> None:
    assert unknown_input.missing_inputs

    result = verify_property_narration(
        "필요한 정보는 모두 확인되었습니다.",
        unknown_input,
        section_key="user_confirmations",
    )

    assert not result.ok
    assert any(item.kind == "missing_input_overreach" for item in result.violations)


def test_affordability_claim_is_allowed_when_a_listing_is_affordable(
    report_input: PropertyReportAIInput,
) -> None:
    """규칙이 판정에 근거한다는 것을 뒤집어 확인한다 — 무조건 금지가 아니다."""
    assert any(
        item.verdict is AffordabilityVerdict.AFFORDABLE
        for item in report_input.handoff.items
    )

    result = verify_property_narration(
        "표시된 판정 가운데 구매할 수 있는 것으로 나온 경우가 있습니다.",
        report_input,
        section_key="affordability_verdicts",
    )

    assert result.ok


# --------------------------------------------------------------------------
# 두 에이전트
# --------------------------------------------------------------------------


def test_both_agents_pass_and_every_section_is_narrated(
    report_input: PropertyReportAIInput,
) -> None:
    report = build_report_from_spec(
        property_narration_spec(report_input),
        writer_client=_writer(),
        judge_client=_judge(),
        settings=_settings(),
    )

    assert report.fully_verified
    assert set(report.adopted_sections) == set(_KEYS)
    assert all(section.narration == _CLEAN for section in report.form.sections)


def test_machine_gate_blocks_a_listing_reference_even_if_the_judge_says_ok(
    report_input: PropertyReportAIInput,
) -> None:
    name = report_input.handoff.items[0].property_name
    assert name is not None

    report = build_report_from_spec(
        property_narration_spec(report_input),
        writer_client=_writer(affordability_verdicts=f"{name}의 판정을 설명합니다."),
        judge_client=_judge(),
        settings=_settings(),
    )

    blocked = next(
        item for item in report.outcomes if item.key == "affordability_verdicts"
    )
    assert not blocked.machine_ok
    assert blocked.blocked_by == "machine"
    assert not report.fully_verified
    # 막혀도 수치는 남는다.
    section = report.form.section("affordability_verdicts")
    assert section is not None and section.figures
    assert section.narration is None


def test_judge_issue_keeps_the_figures(report_input: PropertyReportAIInput) -> None:
    report = build_report_from_spec(
        property_narration_spec(report_input),
        writer_client=_writer(),
        judge_client=_judge(stress_result="ISSUE"),
        settings=_settings(),
    )

    outcome = next(item for item in report.outcomes if item.key == "stress_result")
    assert outcome.machine_ok
    assert outcome.blocked_by == "judge"
    section = report.form.section("stress_result")
    assert section is not None and section.figures and section.narration is None


def test_writer_prompt_never_carries_the_request_profile(
    report_input: PropertyReportAIInput,
) -> None:
    writer = _writer()
    build_report_from_spec(
        property_narration_spec(report_input),
        writer_client=writer,
        judge_client=_judge(),
        settings=_settings(),
    )

    prompt = writer.calls[0]["user_prompt"]
    assert "PRIVATE-PERSONA" not in prompt
    assert writer.calls[0]["response_schema"]["required"] == list(_KEYS)


# --------------------------------------------------------------------------
# 인쇄 문서
# --------------------------------------------------------------------------


def test_print_document_lists_every_listing_not_only_the_capped_ones(
    report_input: PropertyReportAIInput,
) -> None:
    report = build_report_from_spec(
        property_narration_spec(report_input),
        writer_client=_writer(),
        judge_client=_judge(),
        settings=_settings(),
    )

    html = render_property_official_report(report, report_input)

    assert html.startswith("<!doctype html>")
    assert "<meta charset='utf-8'>" in html
    for item in report_input.handoff.items:
        assert item.address_summary in html
    assert "승인" not in html.split("유의사항")[0].replace("대출 승인", "")


def test_print_document_states_the_unknown_contract(
    unknown_input: PropertyReportAIInput,
) -> None:
    report = build_report_from_spec(
        property_narration_spec(unknown_input),
        writer_client=_writer(),
        judge_client=_judge(),
        settings=_settings(),
    )

    html = render_property_official_report(report, unknown_input)

    assert "확인되지 않음은 0이나 해당 없음이 아니며" in html
    assert "판정 불가(입력 부족)" in html
