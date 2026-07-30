"""작성 에이전트 + 검증 에이전트: 둘 다 통과한 절만 서술이 실린다.

핵심 불변식 셋을 고정한다.
1. 기계 검증이 하드 게이트다 — 검증 에이전트가 OK를 줘도 열리지 않는다.
2. 판정을 받지 못한 상태는 통과가 아니다.
3. 어느 쪽이 막아도 **수치는 남는다** — 사용자가 값을 잃지 않는다.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.reports.ai_explanation.gemini import GenerationResult
from app.reports.ai_explanation.pipeline import build_final_report
from app.reports.ai_explanation.verifier_agent import Verdict, judge_report_form
from app.reports.templates.form import FORM_SECTIONS, build_report_form
from app.schemas.report import ReportAIInput

_KEYS = tuple(key for key, _title in FORM_SECTIONS)
_CLEAN = "표시된 수치의 의미를 설명하는 문장입니다."


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
    payload = {
        key: {"verdict": overrides.get(key, default), "reason": ""} for key in _KEYS
    }
    for key, verdict in overrides.items():
        payload[key] = {"verdict": verdict, "reason": f"{key} 지적 사유"}
    return FakeClient(GenerationResult(text=json.dumps(payload, ensure_ascii=False), model="j"))



def _final(report_input: ReportAIInput, writer: FakeClient, judge: FakeClient):
    return build_final_report(
        report_input,
        writer_client=writer,
        judge_client=judge,
        settings=_settings(),
    )


class TestBothAgentsMustAgree:
    def test_both_pass_so_every_section_is_narrated(
        self,
        report_input: ReportAIInput,
    ) -> None:
        report = _final(report_input, _writer(), _judge())

        assert report.fully_verified
        assert report.adopted_sections == _KEYS
        assert _CLEAN in report.to_markdown()

    def test_the_judge_cannot_open_the_machine_gate(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """기계 검증에서 탈락한 절은 **판정자에게 전달되지도 않는다.**

        판정자가 전부 OK라고 답해도 그 절은 실리지 않는다. 기계 검증이 하드
        게이트인 이유는 LLM 판정자가 잘못 통과시킬 수 있기 때문이고, 이미 탈락한
        문장을 판정에 보내는 것은 토큰 낭비이기도 하다.
        """
        offending = "부족액은 66,479,492원입니다."
        report = _final(
            report_input,
            _writer(shortfall_and_extension=offending),
            _judge(),  # 판정자는 전부 OK라고 답한다
        )

        outcome = next(i for i in report.outcomes if i.key == "shortfall_and_extension")
        assert outcome.machine_ok is False
        # 판정 대상에서 제외됐으므로 OK를 받을 기회조차 없다.
        assert outcome.judge_verdict is Verdict.NOT_JUDGED
        assert outcome.adopted is False
        assert outcome.blocked_by == "machine"
        assert offending not in report.to_markdown()

        # 다른 절들은 판정을 받고 정상 채택된다 — 한 절 때문에 전체가 죽지 않는다.
        others = [i for i in report.outcomes if i.key != "shortfall_and_extension"]
        assert all(i.judge_verdict is Verdict.OK and i.adopted for i in others)

    def test_a_judge_issue_drops_the_section_even_if_the_machine_passed(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """의미 오류는 기계가 못 잡으므로 판정자가 막아야 한다."""
        report = _final(report_input, _writer(), _judge(base_vs_stress="ISSUE"))

        outcome = next(i for i in report.outcomes if i.key == "base_vs_stress")
        assert outcome.machine_ok is True
        assert outcome.judge_verdict is Verdict.ISSUE
        assert outcome.adopted is False
        assert outcome.blocked_by == "judge"
        assert not report.fully_verified
        assert any("base_vs_stress" in note for note in report.notes)

    def test_an_unavailable_judge_is_not_treated_as_a_pass(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """판정을 못 받은 상태는 "문제 없음"이 아니라 "모름"이다."""
        broken_judge = FakeClient(
            GenerationResult(text=None, model="j", error="판정 호출 실패")
        )

        report = _final(report_input, _writer(), broken_judge)

        assert report.adopted_sections == ()
        assert all(i.judge_verdict is Verdict.NOT_JUDGED for i in report.outcomes)
        assert not report.fully_verified
        assert any("판정 호출 실패" in note for note in report.notes)

    def test_an_unparseable_verdict_is_not_a_pass(self, report_input: ReportAIInput) -> None:
        weird = FakeClient(
            GenerationResult(
                text=json.dumps({key: {"verdict": "아마도", "reason": ""} for key in _KEYS}),
                model="j",
            )
        )

        report = _final(report_input, _writer(), weird)

        assert report.adopted_sections == ()
        assert all(i.judge_verdict is Verdict.NOT_JUDGED for i in report.outcomes)

    def test_figures_survive_whichever_agent_blocks(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """어느 쪽이 막아도 계산 결과는 사용자에게 도달한다."""
        blocked = _final(report_input, _writer(), _judge(default="ISSUE"))

        assert blocked.adopted_sections == ()
        markdown = blocked.to_markdown()
        assert "283,520,507원" in markdown
        assert "**필요 대출금액 대비** 부족액" in markdown


class TestKnownMisattributionIsBlockedByMachine:
    """LLM 판정자가 놓치는 것을 확인한 오류는 기계가 막는다.

    실제 Gemini 판정자에게 세 가지 함정 문장을 물었을 때 두 개는 ISSUE로 잡았지만
    **이 설계의 출발점이었던 "목표 금액 대비" 오귀속은 OK로 통과시켰다.**
    LLM 판정은 보완이지 보증이 아니므로, 아는 오류는 결정론적으로 막는다.
    """

    def test_the_motivating_misattribution_never_reaches_the_report(
        self,
        report_input: ReportAIInput,
    ) -> None:
        trap = "표시된 부족액은 목표 금액 대비 부족한 금액입니다."
        report = _final(
            report_input,
            _writer(shortfall_and_extension=trap),
            _judge(),  # 판정자는 OK라고 답한다 — 실제 관찰된 동작
        )

        outcome = next(i for i in report.outcomes if i.key == "shortfall_and_extension")
        assert outcome.machine_ok is False
        assert "misattribution" in outcome.machine_reason
        assert trap not in report.to_markdown()

    def test_the_correct_phrasing_passes(self, report_input: ReportAIInput) -> None:
        """금지 표현이 정상 문장을 막지 않는지도 확인한다."""
        fine = "표시된 대출 가능액은 필요 대출금액에 미치지 못합니다."
        report = _final(report_input, _writer(shortfall_and_extension=fine), _judge())

        outcome = next(i for i in report.outcomes if i.key == "shortfall_and_extension")
        assert outcome.adopted is True
        assert fine in report.to_markdown()


class TestJudgeAgent:
    def test_nothing_to_judge_when_no_narration_exists(
        self,
        report_input: ReportAIInput,
    ) -> None:
        bare = build_report_form(report_input)
        client = FakeClient(GenerationResult(text="{}", model="j"))

        result = judge_report_form(bare, client=client, settings=_settings())

        assert client.calls == []
        assert not result.ran
        assert any("판정할 서술이 없습니다" in note for note in result.notes)

    def test_the_prompt_shows_figures_and_narration_only(
        self,
        report_input: ReportAIInput,
    ) -> None:
        """원본 계산 JSON을 판정자에게 주지 않는다."""
        form = build_report_form(report_input, narrations={key: _CLEAN for key in _KEYS})
        client = FakeClient(GenerationResult(text="{}", model="j"))

        judge_report_form(form, client=client, settings=_settings())

        prompt = client.calls[0]["user_prompt"]
        assert _CLEAN in prompt
        assert "283,520,507원" in prompt
        assert "simulation_id" not in prompt
