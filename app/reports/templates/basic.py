"""AI 없이 계산 결과만으로 만드는 고정 보고서.

목적:
    ``reports/README``의 2단계다. AI 호출이 실패하거나 키가 없어도 사용자는
    보고서를 받아야 한다. 그래서 이 모듈은 네트워크·LLM에 의존하지 않는다.
기능:
    ``ReportAIInput``을 사람이 읽는 한국어 절(section) 목록으로 바꾼다.
근거:
    SSOT §19(추천·탈락 사유, 기준일, 기본 vs 스트레스 명시)와 §20(승인·금리
    보장 문구 금지)을 따른다. 여기서 만든 문장은 AI 설명의 **기준선**이기도 하다 —
    검증기가 AI 문장을 이 결과와 같은 사실 집합 안에 있는지로 판단한다.
"""

from dataclasses import dataclass, field

from app.schemas.report import ReportAIInput, ReportSection
from app.schemas.simulation import SectionRunStatus

_SECTION_TITLES: tuple[tuple[str, str], ...] = (
    ("financial_diagnosis", "현금흐름 진단"),
    ("savings", "예·적금"),
    ("loan", "대출"),
    ("recommendation", "종합추천"),
    ("stress_test", "생활 스트레스"),
    ("strategy_comparison", "구매 전략 비교"),
)

_DISCLAIMERS: tuple[str, ...] = (
    "이 보고서는 계산 결과를 설명한 것이며 대출 승인이나 실제 적용금리를 보장하지 않습니다.",
    "UNKNOWN과 결측은 실패나 0이 아니며, 확인하면 결과가 달라질 수 있습니다.",
)


@dataclass(frozen=True)
class ReportBlock:
    """보고서 한 절. 제목과 문장들을 분리해 둬야 AI 설명과 나란히 붙일 수 있다."""

    key: str
    title: str
    lines: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TemplateReport:
    headline: str
    blocks: tuple[ReportBlock, ...]
    policy_sources: tuple[str, ...] = field(default_factory=tuple)
    disclaimers: tuple[str, ...] = _DISCLAIMERS

    def to_text(self) -> str:
        parts = [self.headline, ""]
        for block in self.blocks:
            parts.append(f"## {block.title}")
            parts.extend(block.lines or ("표시할 내용이 없습니다.",))
            parts.append("")
        if self.policy_sources:
            parts.append("## 근거 출처")
            parts.extend(f"- {source}" for source in self.policy_sources)
            parts.append("")
        parts.append("## 유의사항")
        parts.extend(f"- {note}" for note in self.disclaimers)
        return "\n".join(parts).strip()


def _amount(value: object) -> str:
    """금액 문자열을 사람이 읽는 형태로. Decimal은 JSON에서 문자열로 온다."""
    try:
        return f"{int(round(float(str(value)))):,}원"
    except (TypeError, ValueError):
        return str(value)


def _section_lines(section: ReportSection) -> tuple[str, ...]:
    if section.run_status is SectionRunStatus.NOT_RUN:
        lines = ["이 항목은 아직 계산하지 않았습니다."]
        if section.missing_inputs:
            lines.append(f"확인이 필요한 입력: {', '.join(section.missing_inputs)}")
        lines.extend(section.reasons)
        return tuple(lines)

    lines: list[str] = []
    if section.engine_status:
        lines.append(f"상태: {section.engine_status}")
    lines.extend(section.reasons)
    if section.missing_inputs:
        lines.append(f"확인이 필요한 입력: {', '.join(section.missing_inputs)}")
    return tuple(lines)


def _loan_highlight(section: ReportSection) -> tuple[str, ...]:
    """대출 구간에서 사용자가 가장 먼저 볼 숫자만 뽑는다."""
    facts = section.facts
    if not facts:
        return ()
    executable = facts.get("executable")
    if not isinstance(executable, list) or not executable:
        return ()
    lines: list[str] = []
    for option in executable:
        if not isinstance(option, dict):
            continue
        name = option.get("product_name")
        amount = option.get("amount")
        if name is None or amount is None:
            continue
        lines.append(f"- {name}: 최대 {_amount(amount)}")
    return tuple(lines)


def build_template_report(payload: ReportAIInput) -> TemplateReport:
    """계산 결과만으로 고정 보고서를 만든다. 여기서 새 숫자를 만들지 않는다."""
    goal = payload.goal
    headline = (
        f"# 주택자금 계획 보고서 ({payload.as_of.isoformat()} 기준)\n"
        f"목표: {goal.goal_type.value} / {_amount(goal.target_amount)} / "
        f"{goal.target_date.isoformat()}까지"
    )

    blocks: list[ReportBlock] = []
    for key, title in _SECTION_TITLES:
        section: ReportSection = getattr(payload.sections, key)
        lines = list(_section_lines(section))
        if key == "loan":
            lines.extend(_loan_highlight(section))
        blocks.append(ReportBlock(key=key, title=title, lines=tuple(lines)))

    if payload.missing_inputs:
        blocks.append(
            ReportBlock(
                key="missing",
                title="확인이 필요한 항목",
                lines=tuple(f"- {name}" for name in payload.missing_inputs),
            )
        )

    return TemplateReport(
        headline=headline,
        blocks=tuple(blocks),
        policy_sources=payload.policy_sources,
    )


__all__ = ["ReportBlock", "TemplateReport", "build_template_report"]
