"""매물 계산 결과에서 보고서 AI 입력을 만든다.

보고서 AI는 사용자의 요청 원본(프로필·재무 스냅샷)을 보지 않는다. dove가 만든
``PropertyAffordabilityAIHandoff``가 이미 개인정보를 걷어낸 상태이므로 그대로
쓰고, 여기서는 권장 절이 요구하는 검색 조건과 현금흐름 진단만 덧붙인다.

브라우저가 보낸 계산 결과를 쓰지 않는 이유:
    핸드오프 문서가 명시한 주의사항이다. 이 모듈의 입력은 **서버가 방금 실행한**
    응답 객체이며, 클라이언트가 준 숫자를 그대로 신뢰하는 경로는 만들지 않는다.
"""

from datetime import date

from app.engines.cashflow.models import CashflowResult
from app.reports.context import sanitize_report_facts
from app.schemas.property_affordability import PropertyAffordabilitySearchResponse
from app.schemas.property_report import PropertyReportAIInput, PropertyReportDiagnosis
from app.schemas.simulation import SectionRunStatus
from app.services.property_affordability_api import (
    build_property_affordability_ai_handoff,
)
from app.services.simulation_result import to_json_value


def _diagnosis_section(result: CashflowResult | None) -> PropertyReportDiagnosis:
    if result is None:
        return PropertyReportDiagnosis(
            run_status=SectionRunStatus.NOT_RUN,
            reasons=("현금흐름 진단을 실행하지 않았습니다.",),
        )
    facts = sanitize_report_facts(to_json_value(result))
    if not isinstance(facts, dict):
        raise TypeError("현금흐름 진단 결과가 JSON 객체로 직렬화되지 않았습니다.")
    return PropertyReportDiagnosis(
        run_status=SectionRunStatus.COMPLETED,
        engine_status=str(result.status.value),
        facts=facts,
        missing_inputs=result.missing_inputs,
        reasons=tuple(dict.fromkeys(result.reasons + result.assumptions)),
    )


def build_property_report_ai_input(
    response: PropertyAffordabilitySearchResponse,
    *,
    as_of: date,
    cashflow_result: CashflowResult | None = None,
) -> PropertyReportAIInput:
    """서버가 산출한 매물 응답을 보고서 AI 입력으로 바꾼다."""

    return PropertyReportAIInput(
        as_of=as_of,
        criteria=response.search_result.criteria,
        handoff=build_property_affordability_ai_handoff(response),
        financial_diagnosis=_diagnosis_section(cashflow_result),
    )


__all__ = ["build_property_report_ai_input"]
