"""계산 결과를 설명 문장으로 바꾸는 보고서 에이전트.

목적:
    ``reports/README``의 3단계다. 고정 템플릿 보고서에 AI 설명을 **덧붙이되**,
    검증을 통과하지 못하면 붙이지 않는다.
기능:
    게이트(전송 가능 여부) → 프롬프트 → 생성 → 검증 → 채택/폴백.
근거:
    - AI는 숫자·상품명·상태를 바꿀 수 없다(SSOT §20). 프롬프트로 부탁하고,
      출력에서 다시 확인한다(`validation/numbers.py`).
    - AI 호출이 실패해도 고정 템플릿 보고서는 제공된다(`reports/README`).
    - 계산 결과와 AI 문장은 **별도 필드로 보존**한다. 섞으면 나중에 어느 문장이
      검증을 통과한 것인지 알 수 없다.
"""

import json
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.reports.ai_explanation.egress import (
    EgressReport,
    ReportEgressBlocked,
    guard_payload,
)
from app.reports.ai_explanation.gemini import ExplanationClient, GeminiClient
from app.reports.templates.basic import TemplateReport, build_template_report
from app.reports.validation.numbers import VerificationResult, verify_explanation
from app.schemas.report import ReportAIInput

_SYSTEM_PROMPT = """\
당신은 주택자금 계획 보고서의 설명을 쓰는 작성자입니다. 계산은 이미 끝났습니다.

반드시 지킬 것:
1. 입력 JSON에 있는 금액·비율·점수·상품명·상태만 사용합니다. 새 수치를 만들거나
   더하거나 다시 계산하지 않습니다. 평균·합계·차이도 직접 계산하지 마십시오.
   특히 **월 상환액, 총이자, LTV·DTI·DSR 비율은 절대 직접 계산하지 마십시오.**
   입력 JSON에 그 값이 없으면 수치를 쓰지 말고 "계산 결과에 포함되지 않았습니다"
   라고 서술합니다. 일반 상식이나 통상적인 규제 비율을 끌어오지 마십시오 —
   지역·차주 조건에 따라 다르며 틀리면 사용자가 잘못된 판단을 합니다.
   쓰려는 수치가 입력 JSON에 문자 그대로 있는지 확인한 뒤에만 쓰십시오.
2. 금액은 반드시 천단위 쉼표와 "원"을 붙여 씁니다(예: 283,520,507원).
   비율은 반드시 "%"를 붙여 씁니다. 단위 없는 수치는 쓰지 마십시오.
3. null 또는 UNKNOWN은 실패나 0이 아닙니다. "확인이 필요하다"고 서술합니다.
4. 대출 승인, 상품 가입, 미래 집값·금리를 보장하는 표현을 쓰지 않습니다.
5. 입력에 없는 상품을 언급하지 않습니다. 상품명은 입력에 적힌 그대로 씁니다.
6. 날짜는 입력의 기준일·목표일만 사용합니다.

혼동하기 쉬운 필드의 뜻입니다. **수치를 어떤 기준으로 설명하는지가 틀리면
값이 맞아도 사용자를 오해시킵니다.**
- goal.target_amount: 주택 목표 금액 전체입니다. 대출로 조달할 금액이 아닙니다.
- required_amount: 목표 금액에서 자기자본을 뺀 **필요 대출금액**입니다.
- funding_shortfall: `required_amount` 대비 부족액입니다.
  **"목표 금액 대비"라고 쓰지 마십시오.** 필요 대출금액 대비입니다.
- maximum_amount / recommended_amount: 계산된 대출 가능액입니다. 승인액이 아닙니다.
- monthly_payment: 실제 금리로 계산한 월 상환액입니다. 사용자가 실제로 낼 금액입니다.
- stress_monthly_payment: **심사용** 금리로 계산한 값입니다. 실제 상환액이 아니므로
  "월 상환액"으로 소개하지 마십시오.
- annual_rate는 실제 금리, assessment_annual_rate는 심사용 금리입니다. 섞지 마십시오.
- expected_dsr: 기준 시점 DSR입니다. stress_test의 maximum_dsr은 충격 시나리오의
  최악값이므로 둘을 같은 것으로 쓰지 마십시오.
- safe_dsr: 법정 상한이 아니라 서비스 내부 안전기준입니다. 그렇게 밝혀 쓰십시오.

출력 형식: 마크다운. 다음 세 절만 씁니다.
## 요약
## 지금 확인해야 할 것
## 주의할 점

각 절은 3~5개의 짧은 문단 또는 불릿으로 씁니다. 한국어로 씁니다.
"""


@dataclass(frozen=True)
class ExplainedReport:
    """고정 보고서와 AI 설명을 분리해 담는다."""

    template: TemplateReport
    explanation: str | None = None
    model: str | None = None
    adopted: bool = False
    # 채택하지 않았을 때의 사유. 사용자에게 "AI 설명 없음"만 보여주지 않는다.
    notes: tuple[str, ...] = field(default_factory=tuple)
    verification: VerificationResult | None = None
    egress: EgressReport | None = None

    def to_text(self) -> str:
        base = self.template.to_text()
        if self.adopted and self.explanation:
            return f"{base}\n\n---\n\n{self.explanation.strip()}"
        return base


def build_user_prompt(payload: ReportAIInput) -> str:
    """생성 규칙과 계산 결과를 하나의 사용자 메시지로 만든다."""
    facts = json.dumps(payload.to_json_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    rules = "\n".join(f"- {rule}" for rule in payload.generation_rules)
    return (
        "아래 계산 결과만 사용해 보고서 설명을 작성하십시오.\n\n"
        f"[이 결과에 붙은 생성 규칙]\n{rules}\n\n"
        f"[계산 결과 JSON]\n{facts}\n"
    )


def explain_report(
    payload: ReportAIInput,
    *,
    client: ExplanationClient | None = None,
    settings: Settings | None = None,
) -> ExplainedReport:
    """계산 결과에 AI 설명을 붙인다. 실패·위반 시 고정 보고서만 돌려준다."""
    resolved = settings or get_settings()
    template = build_template_report(payload)
    notes: list[str] = []

    try:
        egress = guard_payload(
            payload.to_json_dict(),
            enabled=resolved.report_ai_egress_guard,
        )
    except ReportEgressBlocked as blocked:
        # 여기서 멈추는 것이 정상 동작이다. 외부로 나가면 되돌릴 수 없다.
        return ExplainedReport(
            template=template,
            adopted=False,
            notes=(
                "개인정보로 보이는 값이 있어 외부 AI에 전송하지 않았습니다.",
                str(blocked),
            ),
            egress=EgressReport(allowed=False, findings=blocked.findings),
        )

    if not egress.allowed:
        # 게이트를 끈 상태다. 전송은 하지만 무엇이 걸렸는지는 남긴다.
        notes.append(
            "전송 게이트가 비활성화된 상태에서 식별자 의심 값이 발견됐습니다: "
            + ", ".join(f"{item.path}({item.kind})" for item in egress.findings)
        )

    resolved_client = client or GeminiClient(resolved)
    generated = resolved_client.generate(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=build_user_prompt(payload),
    )
    notes.extend(generated.request_notes)

    if not generated.ok or generated.text is None:
        notes.append(generated.error or "AI 설명을 생성하지 못했습니다.")
        return ExplainedReport(
            template=template,
            model=generated.model,
            adopted=False,
            notes=tuple(notes),
            egress=egress,
        )

    verification = verify_explanation(generated.text, payload)
    if not verification.ok:
        notes.append(
            "AI 설명이 검증을 통과하지 못해 채택하지 않았습니다: "
            + ", ".join(
                f"{item.kind}={item.value}" for item in verification.violations[:5]
            )
        )
        return ExplainedReport(
            template=template,
            explanation=generated.text,
            model=generated.model,
            adopted=False,
            notes=tuple(notes),
            verification=verification,
            egress=egress,
        )

    return ExplainedReport(
        template=template,
        explanation=generated.text,
        model=generated.model,
        adopted=True,
        notes=tuple(notes),
        verification=verification,
        egress=egress,
    )


__all__ = ["ExplainedReport", "build_user_prompt", "explain_report"]
