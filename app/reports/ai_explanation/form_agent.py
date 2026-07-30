"""SSOT §19 고정 양식의 서술 칸만 AI에게 채우게 하는 에이전트.

목적:
    구조와 수치는 엔진이 확정하고, AI는 각 절의 **문장**만 쓴다.
기능:
    구조화 출력(JSON)으로 절별 서술을 받고, 칸마다 따로 검증한다. 통과한 칸만
    양식에 채우고 실패한 칸은 비워 둔다 — 한 칸이 틀려서 보고서 전체를 버리지
    않는다.
근거:
    자유 서술판(`agent.py`)에서 값은 맞지만 귀속이 틀린 문장이 검증을 통과했다
    ("목표 금액 대비 66,479,492원 부족", 실은 필요 대출금액 대비). 서술 칸에서
    수치를 아예 금지하면 그 오류가 **구조적으로** 불가능해진다.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.reports.ai_explanation.egress import (
    EgressReport,
    ReportEgressBlocked,
    guard_payload,
)
from app.reports.ai_explanation.gemini import ExplanationClient, GeminiClient
from app.reports.templates.form import FORM_SECTIONS, ReportForm, build_report_form
from app.reports.validation.numbers import VerificationResult, verify_narration
from app.schemas.report import ReportAIInput

_SYSTEM_PROMPT = """\
당신은 주택자금 계획 보고서의 **설명 문장**을 쓰는 작성자입니다.
계산은 이미 끝났고, 수치는 보고서에 이미 표시되어 있습니다.

당신의 역할은 각 절의 수치가 **무슨 의미인지** 설명하는 것입니다.

절대 규칙:
1. **숫자를 쓰지 마십시오.** 금액, 비율, 퍼센트, 날짜, 개수를 쓰면 안 됩니다.
   수치는 보고서가 이미 보여주므로 반복할 필요가 없습니다.
   "표시된 금액", "위 비율", "해당 시나리오"처럼 가리켜 말하십시오.
2. 입력에 없는 상품을 언급하지 마십시오.
3. 대출 승인, 상품 가입, 미래 집값·금리를 보장하는 표현을 쓰지 마십시오.
4. null과 UNKNOWN은 실패나 0이 아닙니다. "확인이 필요하다"고 서술합니다.
5. 각 절은 2~3문장으로 짧게 씁니다. 한국어 존댓말로 씁니다.
6. 계산되지 않은 절은 무엇을 확인해야 계산되는지 설명하십시오.

절대 하지 말 것의 예:
  나쁨: "최대 283,520,507원을 받을 수 있어 3억 5천만원 대비 부족합니다."
  좋음: "표시된 대출 가능액은 필요 대출금액에 미치지 못합니다. 부족한 만큼은
        자기자본이나 다른 조달 수단으로 메워야 합니다."
"""

_SECTION_GUIDE: dict[str, str] = {
    "decision_reasons": "어떤 상품이 왜 추천되었고 왜 빠졌는지, 그 판정이 무엇을 뜻하는지.",
    "rates_and_policy": (
        "실제 적용 금리와 심사용 금리가 다른 이유. 심사용 금리는 한도를 정할 때만 쓰며 "
        "실제로 내는 금액이 아니라는 점을 반드시 설명하십시오."
    ),
    "preferential_rate": "우대금리 조건이 결과에 어떤 영향을 주는지, 확인이 필요한 이유.",
    "base_vs_stress": (
        "기본 조건과 스트레스 조건의 차이가 사용자에게 무슨 의미인지. "
        "스트레스는 규제 심사가 아니라 생활 안정성 점검이라는 점을 밝히십시오."
    ),
    "shortfall_and_extension": "부족액을 메우는 방법과 목표 시점을 늦출 때의 고려사항.",
    "user_confirmations": "사용자가 직접 확인해야 하는 이유와 확인하지 않으면 생기는 위험.",
}


@dataclass(frozen=True)
class FormReport:
    form: ReportForm
    model: str | None = None
    # 칸별 채택 여부. 한 칸이 실패해도 나머지는 살린다.
    adopted_sections: tuple[str, ...] = field(default_factory=tuple)
    rejected_sections: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)
    verifications: dict[str, VerificationResult] = field(default_factory=dict)
    egress: EgressReport | None = None

    @property
    def fully_narrated(self) -> bool:
        return len(self.adopted_sections) == len(FORM_SECTIONS)

    def to_text(self) -> str:
        return self.form.to_text()


def narration_response_schema() -> dict[str, Any]:
    """절 키를 그대로 필드로 갖는 구조화 출력 스키마."""
    return {
        "type": "object",
        "properties": {key: {"type": "string"} for key, _title in FORM_SECTIONS},
        "required": [key for key, _title in FORM_SECTIONS],
        "propertyOrdering": [key for key, _title in FORM_SECTIONS],
    }


def build_form_prompt(payload: ReportAIInput, form: ReportForm) -> str:
    """각 절의 제목·수치·서술 지침을 함께 넘긴다.

    계산 결과 전체가 아니라 **양식에 이미 렌더링된 수치 줄**을 보여준다. AI가
    설명할 대상이 그것이고, 원본 JSON을 다 주면 거기서 다른 수치를 끌어오려 한다.
    """
    blocks: list[str] = []
    for section in form.sections:
        figures = "\n".join(f"    {line}" for line in section.figures) or "    (없음)"
        blocks.append(
            f"[{section.key}] {section.title}\n"
            f"  보고서에 표시된 수치:\n{figures}\n"
            f"  이 절에서 설명할 것: {_SECTION_GUIDE[section.key]}"
        )
    rules = "\n".join(f"- {rule}" for rule in payload.generation_rules)
    missing = ", ".join(payload.missing_inputs) or "없음"
    return (
        "아래 각 절의 서술 칸을 채우십시오. 숫자는 쓰지 마십시오.\n\n"
        f"[이 결과에 붙은 생성 규칙]\n{rules}\n\n"
        f"[확인되지 않은 입력]\n{missing}\n\n"
        + "\n\n".join(blocks)
    )


def explain_report_form(
    payload: ReportAIInput,
    *,
    client: ExplanationClient | None = None,
    settings: Settings | None = None,
) -> FormReport:
    """고정 양식을 만들고 서술 칸을 AI로 채운다. 실패한 칸은 비워 둔다."""
    resolved = settings or get_settings()
    bare_form = build_report_form(payload)

    try:
        egress = guard_payload(
            payload.to_json_dict(),
            enabled=resolved.report_ai_egress_guard,
        )
    except ReportEgressBlocked as blocked:
        return FormReport(
            form=bare_form,
            notes=(
                "개인정보로 보이는 값이 있어 외부 AI에 전송하지 않았습니다.",
                str(blocked),
            ),
            egress=EgressReport(allowed=False, findings=blocked.findings),
        )

    notes: list[str] = []
    resolved_client = client or GeminiClient(resolved)
    generated = resolved_client.generate(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=build_form_prompt(payload, bare_form),
        response_schema=narration_response_schema(),
    )
    notes.extend(generated.request_notes)

    if not generated.ok or generated.text is None:
        notes.append(generated.error or "AI 설명을 생성하지 못했습니다.")
        return FormReport(form=bare_form, model=generated.model, notes=tuple(notes), egress=egress)

    try:
        parsed = json.loads(generated.text)
    except json.JSONDecodeError:
        notes.append("AI 응답이 JSON 형식이 아니어서 서술을 채우지 않았습니다.")
        return FormReport(form=bare_form, model=generated.model, notes=tuple(notes), egress=egress)
    if not isinstance(parsed, dict):
        notes.append("AI 응답이 절별 객체가 아니어서 서술을 채우지 않았습니다.")
        return FormReport(form=bare_form, model=generated.model, notes=tuple(notes), egress=egress)

    accepted: dict[str, str] = {}
    adopted: list[str] = []
    rejected: list[str] = []
    verifications: dict[str, VerificationResult] = {}
    for key, _title in FORM_SECTIONS:
        value = parsed.get(key)
        if not isinstance(value, str) or not value.strip():
            rejected.append(key)
            notes.append(f"{key}: 서술이 비어 있어 채우지 않았습니다.")
            continue
        result = verify_narration(value, payload, section_key=key)
        verifications[key] = result
        if result.ok:
            accepted[key] = value.strip()
            adopted.append(key)
            continue
        rejected.append(key)
        notes.append(
            f"{key}: 검증 실패로 채우지 않았습니다 — "
            + ", ".join(f"{item.kind}={item.value}" for item in result.violations[:3])
        )

    return FormReport(
        form=build_report_form(payload, narrations=accepted),
        model=generated.model,
        adopted_sections=tuple(adopted),
        rejected_sections=tuple(rejected),
        notes=tuple(notes),
        verifications=verifications,
        egress=egress,
    )


__all__ = [
    "FORM_SECTIONS",
    "FormReport",
    "build_form_prompt",
    "explain_report_form",
    "narration_response_schema",
]
