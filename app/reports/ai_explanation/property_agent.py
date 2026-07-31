"""매물 보고서의 작성 계약(프롬프트·절 지침·검증기).

목표금액 보고서와 **같은 파이프라인**을 쓴다(`explain_form` → 기계 검증 →
판정 에이전트 → 조합). 달라지는 것은 이 파일이 정의하는 세 가지뿐이다:
쓰지 말아야 할 것을 알려 주는 시스템 프롬프트, 절별 지침, 그리고 매물 전용
기계 검증기.

프롬프트에서 매물 지목을 금지하는 이유:
    검증기가 어차피 막지만, 프롬프트에서 미리 말해 주지 않으면 AI가 매번
    매물명을 쓰고 매번 칸이 비어 결과가 나빠진다. 규칙은 두 곳에 같은 내용으로
    적되 **강제는 검증기에서만** 한다.
"""

from collections.abc import Mapping

from app.reports.spec import NarrationSpec
from app.reports.templates.form import ReportForm
from app.reports.templates.property_form import (
    PROPERTY_FORM_SECTIONS,
    build_property_report_form,
)
from app.reports.validation.property_narration import verify_property_narration
from app.schemas.property_report import PropertyReportAIInput

_SYSTEM_PROMPT = """\
당신은 매물별 구매 가능성 보고서의 **설명 문장**을 쓰는 작성자입니다.
계산은 이미 끝났고, 매물별 수치와 판정은 보고서에 이미 표시되어 있습니다.

당신의 역할은 각 절의 수치가 **무슨 의미인지** 설명하는 것입니다.

절대 규칙:
1. **숫자를 쓰지 마십시오.** 금액, 비율, 퍼센트, 날짜, 건수를 쓰면 안 됩니다.
   "표시된 금액", "위 판정"처럼 가리켜 말하십시오.
2. **특정 매물을 지목하지 마십시오.** 매물명, 주소, 매물 번호를 쓰면 안 됩니다.
   매물별 값은 위 수치 줄이 이미 매물명과 함께 보여 줍니다. 당신은 그 목록
   전체를 놓고 "어떻게 읽어야 하는지"를 설명합니다.
3. 조달 후보에 없는 대출 상품을 언급하지 마십시오.
4. 대출 승인, 매물 거래 성사, 미래 집값·금리를 보장하는 표현을 쓰지 마십시오.
5. 판정 불가(UNKNOWN)와 판정 대상 아님(UNSUPPORTED)은 **구매 불가가 아닙니다.**
   구매 가능도 아닙니다. "이 계산으로는 판단하지 못했다"고 서술하십시오.
6. 누락된 입력이 남아 있으면 해결된 것처럼 쓰지 마십시오.
7. 각 절은 2~3문장으로 짧게, 한국어 존댓말로 씁니다.

나쁜 예: "마포 래미안은 구매할 수 있고 나머지 3건은 자금이 부족합니다."
좋은 예: "구매 가능으로 판정된 매물과 자금이 부족한 매물이 함께 나왔습니다.
        판정은 표시된 총구매비용과 조달 가능액의 차이에서 나온 것입니다."
"""

_SECTION_GUIDE: dict[str, str] = {
    "search_and_data": (
        "검색 조건이 결과 범위를 어떻게 좁혔는지, 매물 데이터가 특정 시점의 "
        "스냅샷이라는 점이 왜 중요한지."
    ),
    "financial_diagnosis": (
        "안전 소득·지출과 비상자금 목표가 매물 구매 판단에 어떻게 쓰이는지. "
        "비상자금은 구매에 쓸 수 없는 몫이라는 점을 밝히십시오."
    ),
    "purchase_costs": (
        "총구매비용이 매매가보다 큰 이유와, 총액을 확정하지 못한 항목이 있으면 "
        "그 값이 왜 아직 열려 있는지."
    ),
    "loan_funding": (
        "필요 대출금액이 어떻게 정해지고 조달 가능액이 무엇에 막히는지, "
        "부족액이 뜻하는 것."
    ),
    "affordability_verdicts": (
        "판정 구분이 각각 무슨 뜻인지. 판정 불가와 판정 대상 아님이 구매 불가가 "
        "아니라는 점을 반드시 설명하십시오."
    ),
    "monthly_burden": (
        "월 상환액과 구매 후 잉여현금을 함께 봐야 하는 이유. 잉여현금이 음수면 "
        "무엇을 뜻하는지."
    ),
    "stress_result": (
        "스트레스 조건이 규제 심사가 아니라 생활 안정성 점검이라는 점과, "
        "그 결과를 어떻게 읽어야 하는지."
    ),
    "user_confirmations": (
        "사용자가 직접 확인해야 하는 이유와, 확인하지 않으면 결과가 어떻게 "
        "달라질 수 있는지."
    ),
    "comparison_summary": (
        "판정 분포를 어떻게 읽어야 하는지. 이 보고서가 매물 사이의 우열을 "
        "정하지 않는다는 점을 밝히십시오."
    ),
}


def property_narration_spec(payload: PropertyReportAIInput) -> NarrationSpec:
    """매물 보고서의 작성 계약."""

    def _build(narrations: Mapping[str, str] | None) -> ReportForm:
        return build_property_report_form(payload, narrations=dict(narrations or {}))

    return NarrationSpec(
        sections=PROPERTY_FORM_SECTIONS,
        guides=_SECTION_GUIDE,
        system_prompt=_SYSTEM_PROMPT,
        generation_rules=payload.generation_rules,
        missing_inputs=payload.missing_inputs,
        egress_payload=payload.to_json_dict(),
        build_form=_build,
        verify=lambda text, key: verify_property_narration(text, payload, section_key=key),
    )


__all__ = ["property_narration_spec"]
