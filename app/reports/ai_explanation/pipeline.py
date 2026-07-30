"""작성 에이전트와 검증 에이전트를 잇고 최종 보고서를 조합한다.

흐름:
    작성 에이전트 → 기계 검증(하드 게이트) → 검증 에이전트(의미) → 조합

두 에이전트가 모두 통과한 절만 서술을 싣는다. 하나라도 통과하지 못하면 그 절은
**수치만** 실린다 — 보고서 전체를 버리지 않고, 사용자가 값을 잃지도 않는다.

왜 기계 검증을 앞에 두는가:
    LLM 판정자는 잘못 통과시킬 수 있다. 기계 검증은 "서술 칸에 수치가 있으면
    위반"이라는 반박 불가능한 규칙이므로 이걸 하드 게이트로 쓴다. 판정 에이전트는
    그 위에 의미 검사를 **더하는** 역할이며 게이트를 열어 줄 수는 없다.

왜 판정을 못 받으면 통과가 아닌가:
    "두 에이전트가 모두 올바른 답을 냈을 때만 조합한다"는 요구를 그대로 따른다.
    판정을 받지 못한 상태(키 없음·호출 실패)는 "문제 없음"이 아니라 "모름"이며,
    이 저장소는 모름을 통과로 뭉개지 않는다(§22.1).
"""

from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.reports.ai_explanation.egress import EgressReport
from app.reports.ai_explanation.form_agent import FormReport, explain_report_form
from app.reports.ai_explanation.gemini import ExplanationClient
from app.reports.ai_explanation.verifier_agent import (
    JudgementReport,
    SectionJudgement,
    Verdict,
    judge_report_form,
)
from app.reports.templates.form import ReportForm, build_report_form
from app.schemas.report import ReportAIInput


@dataclass(frozen=True)
class SectionOutcome:
    """절 하나에 대한 두 에이전트의 판단."""

    key: str
    title: str
    machine_ok: bool
    machine_reason: str = ""
    judge_verdict: Verdict = Verdict.NOT_JUDGED
    judge_reason: str = ""
    adopted: bool = False

    @property
    def blocked_by(self) -> str | None:
        if self.adopted:
            return None
        if not self.machine_ok:
            return "machine"
        if self.judge_verdict is not Verdict.OK:
            return "judge"
        return None


@dataclass(frozen=True)
class FinalReport:
    """사용자 화면에 띄울 최종 보고서."""

    form: ReportForm
    outcomes: tuple[SectionOutcome, ...] = field(default_factory=tuple)
    writer_model: str | None = None
    judge_model: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    egress: EgressReport | None = None

    @property
    def adopted_sections(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.outcomes if item.adopted)

    @property
    def figures_only_sections(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.outcomes if not item.adopted)

    @property
    def fully_verified(self) -> bool:
        """모든 절이 두 에이전트를 통과했는가."""
        return bool(self.outcomes) and all(item.adopted for item in self.outcomes)

    def to_markdown(self) -> str:
        return self.form.to_text()


def _outcome(
    key: str,
    title: str,
    *,
    writer: FormReport,
    judgement: JudgementReport,
) -> SectionOutcome:
    machine = writer.verifications.get(key)
    machine_ok = key in writer.adopted_sections
    machine_reason = ""
    if machine is not None and not machine.ok:
        machine_reason = ", ".join(
            f"{item.kind}={item.value}" for item in machine.violations[:3]
        )
    elif not machine_ok:
        machine_reason = "작성 에이전트가 서술을 만들지 못했습니다."

    verdict: SectionJudgement = judgement.verdict_for(key)
    return SectionOutcome(
        key=key,
        title=title,
        machine_ok=machine_ok,
        machine_reason=machine_reason,
        judge_verdict=verdict.verdict,
        judge_reason=verdict.reason,
        adopted=machine_ok and verdict.ok,
    )


def build_final_report(
    payload: ReportAIInput,
    *,
    writer_client: ExplanationClient | None = None,
    judge_client: ExplanationClient | None = None,
    settings: Settings | None = None,
) -> FinalReport:
    """두 에이전트를 돌리고 둘 다 통과한 절만 서술을 실어 최종 보고서를 만든다."""
    resolved = settings or get_settings()
    writer = explain_report_form(payload, client=writer_client, settings=resolved)
    notes = list(writer.notes)

    # 작성 에이전트가 기계 검증을 통과시킨 서술만 판정 대상이다.
    judgement = judge_report_form(
        writer.form,
        client=judge_client,
        settings=resolved,
    )
    if judgement.error:
        notes.append(f"검증 에이전트: {judgement.error}")
    notes.extend(judgement.notes)

    outcomes = tuple(
        _outcome(section.key, section.title, writer=writer, judgement=judgement)
        for section in writer.form.sections
    )
    adopted = {
        item.key: writer.form.section(item.key).narration  # type: ignore[union-attr]
        for item in outcomes
        if item.adopted
    }
    for item in outcomes:
        if item.adopted:
            continue
        blocked = item.blocked_by
        if blocked == "judge" and item.judge_reason:
            notes.append(f"{item.key}: 검증 에이전트 지적 — {item.judge_reason}")

    return FinalReport(
        form=build_report_form(
            payload,
            narrations={key: value for key, value in adopted.items() if value},
        ),
        outcomes=outcomes,
        writer_model=writer.model,
        judge_model=judgement.model,
        notes=tuple(dict.fromkeys(notes)),
        egress=writer.egress,
    )


__all__ = ["FinalReport", "SectionOutcome", "build_final_report"]
