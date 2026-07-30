"""서술이 수치를 올바르게 설명했는지 판정하는 검증 에이전트.

목적:
    기계 검증이 원리적으로 못 잡는 **의미 오류**를 잡는다. 정규식은 "그 수가
    계산 결과에 있는가"만 볼 수 있어서, 값은 맞고 **귀속만 틀린** 문장을 통과시킨다
    — 실제로 "목표 금액 대비 66,479,492원 부족"(실은 필요 대출금액 대비)이 통과했다.

기능:
    절별로 (수치 줄, 서술)을 주고 서술이 그 수치를 오해 없이 설명했는지 판정한다.
    구조화 출력으로 절마다 OK/ISSUE와 사유를 받는다.

근거:
    이 에이전트는 기계 검증을 **대체하지 않는다.** LLM 판정자는 잘못 통과시킬 수
    있으므로 순서가 중요하다 — 기계 검증(`verify_narration`)이 하드 게이트로
    앞에 서고, 이 판정은 그 뒤에 더해진다. 판정을 못 했으면 통과로 보지 않는다.
"""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.config import Settings, get_settings
from app.reports.ai_explanation.gemini import ExplanationClient, GeminiClient
from app.reports.templates.form import ReportForm

_SYSTEM_PROMPT = """\
당신은 금융 보고서 감수자입니다. 문장을 고치지 말고 **판정만** 하십시오.

각 절에는 계산 엔진이 산출한 수치 줄과, 작성자가 쓴 설명 문장이 있습니다.
설명 문장이 그 수치를 오해 없이 설명했는지 판정하십시오.

ISSUE로 판정할 것:
1. 수치의 **기준을 잘못 귀속**한 경우. 예: 부족액이 필요 대출금액 대비인데
   "목표 금액 대비"라고 설명한 경우. 값이 맞아도 기준이 틀리면 ISSUE입니다.
2. 심사용 금리를 실제로 내는 금리처럼 설명한 경우, 또는 그 반대.
3. 기본 조건 수치와 스트레스 조건 수치를 뒤바꿔 설명한 경우.
4. UNKNOWN·결측을 "0" 또는 "불가능"으로 단정한 경우.
5. 수치 줄에 없는 사실을 새로 주장한 경우.
6. 대출 승인·미래 금리·미래 집값을 보장하는 표현.
7. 수치 줄과 문장이 서로 모순되는 경우.

OK로 판정할 것:
- 수치를 직접 쓰지 않고 "표시된 금액"처럼 가리켜 말하는 것은 정상입니다.
  설명 문장에 숫자가 없는 것은 의도된 설계이므로 ISSUE가 아닙니다.
- 계산되지 않은 절에서 "확인이 필요하다"고 서술하는 것은 정상입니다.
- 문장이 짧거나 일반적인 것은 ISSUE가 아닙니다. 틀린 것만 ISSUE입니다.

reason은 ISSUE일 때만 한 문장으로 쓰고, OK면 빈 문자열로 두십시오.
확실하지 않으면 ISSUE로 두고 왜 확신할 수 없는지 쓰십시오.
"""


class Verdict(StrEnum):
    OK = "OK"
    ISSUE = "ISSUE"
    # 판정 자체를 받지 못한 상태. 통과로 취급하지 않는다.
    NOT_JUDGED = "NOT_JUDGED"


@dataclass(frozen=True)
class SectionJudgement:
    key: str
    verdict: Verdict
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.verdict is Verdict.OK


@dataclass(frozen=True)
class JudgementReport:
    judgements: dict[str, SectionJudgement] = field(default_factory=dict)
    model: str | None = None
    error: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ran(self) -> bool:
        return self.error is None and bool(self.judgements)

    def verdict_for(self, key: str) -> SectionJudgement:
        return self.judgements.get(
            key,
            SectionJudgement(key=key, verdict=Verdict.NOT_JUDGED, reason="판정을 받지 못했습니다."),
        )


def judgement_response_schema(keys: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            key: {
                "type": "object",
                "properties": {
                    "verdict": {"type": "string", "enum": ["OK", "ISSUE"]},
                    "reason": {"type": "string"},
                },
                "required": ["verdict", "reason"],
                "propertyOrdering": ["verdict", "reason"],
            }
            for key in keys
        },
        "required": list(keys),
        "propertyOrdering": list(keys),
    }


def build_judgement_prompt(form: ReportForm) -> str:
    """판정 대상만 넘긴다. 원본 계산 JSON은 주지 않는다.

    감수자가 봐야 하는 것은 "이 수치 줄과 이 문장이 맞는가"다. 원본 JSON을 주면
    거기서 다른 수치를 끌어와 새 주장을 만들기 시작한다.
    """
    blocks: list[str] = []
    for section in form.sections:
        if not section.narration:
            continue
        figures = "\n".join(f"    {line}" for line in section.figures) or "    (없음)"
        blocks.append(
            f"[{section.key}] {section.title}\n"
            f"  계산 엔진이 산출한 수치:\n{figures}\n"
            f"  작성자의 설명 문장:\n    {section.narration.strip()}"
        )
    return "각 절을 판정하십시오.\n\n" + "\n\n".join(blocks)


def judge_report_form(
    form: ReportForm,
    *,
    client: ExplanationClient | None = None,
    settings: Settings | None = None,
) -> JudgementReport:
    """서술이 채워진 절들을 판정한다. 서술이 없으면 판정할 것도 없다."""
    keys = tuple(section.key for section in form.sections if section.narration)
    if not keys:
        return JudgementReport(notes=("판정할 서술이 없습니다.",))

    resolved = settings or get_settings()
    resolved_client = client or GeminiClient(resolved)
    generated = resolved_client.generate(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=build_judgement_prompt(form),
        response_schema=judgement_response_schema(keys),
    )
    if not generated.ok or generated.text is None:
        return JudgementReport(
            model=generated.model,
            error=generated.error or "판정을 생성하지 못했습니다.",
            notes=generated.request_notes,
        )

    try:
        parsed = json.loads(generated.text)
    except json.JSONDecodeError:
        return JudgementReport(
            model=generated.model,
            error="판정 응답이 JSON 형식이 아닙니다.",
        )
    if not isinstance(parsed, dict):
        return JudgementReport(
            model=generated.model,
            error="판정 응답이 절별 객체가 아닙니다.",
        )

    judgements: dict[str, SectionJudgement] = {}
    for key in keys:
        item = parsed.get(key)
        if not isinstance(item, dict):
            judgements[key] = SectionJudgement(
                key=key,
                verdict=Verdict.NOT_JUDGED,
                reason="판정 항목이 없습니다.",
            )
            continue
        raw = str(item.get("verdict", "")).strip().upper()
        reason = str(item.get("reason", "")).strip()
        if raw == Verdict.OK.value:
            judgements[key] = SectionJudgement(key=key, verdict=Verdict.OK, reason=reason)
        elif raw == Verdict.ISSUE.value:
            judgements[key] = SectionJudgement(
                key=key,
                verdict=Verdict.ISSUE,
                reason=reason or "판정자가 문제를 지적했습니다.",
            )
        else:
            # 알 수 없는 판정값을 OK로 읽지 않는다.
            judgements[key] = SectionJudgement(
                key=key,
                verdict=Verdict.NOT_JUDGED,
                reason=f"해석할 수 없는 판정값입니다: {raw or '(빈 값)'}",
            )
    return JudgementReport(judgements=judgements, model=generated.model)


__all__ = [
    "JudgementReport",
    "SectionJudgement",
    "Verdict",
    "build_judgement_prompt",
    "judge_report_form",
    "judgement_response_schema",
]
