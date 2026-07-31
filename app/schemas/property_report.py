"""매물별 보고서 AI에 허용할 최소 JSON 계약.

핸드오프 문서 8항 1)이 요구한 ``PropertyReportAIInput v1``이다. 기존
``ReportAIInput``을 고치지 않고 **별도 계약**으로 둔다 — 두 보고서는 축이
다르다. 목표금액 보고서의 축은 하나의 목표이고, 매물 보고서의 축은 N개의 매물이다.
한 계약에 밀어 넣으면 절마다 "지금 어느 축인가"를 다시 물어야 한다.

무엇을 싣는가:
    - ``handoff``: 계산이 끝난 매물별 사실(``PropertyAffordabilityAIHandoff``).
      이 값은 dove가 정의했고 이미 개인정보를 걷어낸 상태다. 그대로 싣는다.
    - ``criteria``: 검색 조건. 핸드오프에 없지만 권장 절 1(검색 조건과 데이터
      기준시점)에 필요하고, 지역코드·가격범위·면적범위뿐이라 개인 식별 정보가 아니다.
    - ``financial_diagnosis``: 사용자 현금흐름 진단 요약. 권장 절 2에 필요하다.

``financial_diagnosis``를 실으면 핸드오프의 개인정보 최소화가 약해지지 않는가:
    핸드오프 자체는 그대로 둔다. 여기서 더하는 것은 **엔진 산출 결과**이며,
    같은 항목이 목표금액 보고서(``ReportAIInput.sections.financial_diagnosis``)에서
    이미 같은 외부 전송 검사(``egress``)를 거쳐 나가고 있다. 두 보고서가 같은
    사실을 다르게 취급하면 어느 쪽 기준이 옳은지 알 수 없게 된다.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.property import PropertySearchCriteria
from app.schemas.property_affordability import PropertyAffordabilityAIHandoff
from app.schemas.simulation import JsonValue, SectionRunStatus

PROPERTY_REPORT_AI_INPUT_SCHEMA_VERSION = "1.0.0"


class PropertyReportDiagnosis(BaseModel):
    """현금흐름 진단 결과 요약. 계산하지 않았으면 ``facts``가 없다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_status: SectionRunStatus
    engine_status: str | None = None
    facts: dict[str, JsonValue] | None = None
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


class PropertyReportAIInput(BaseModel):
    """AI가 매물 보고서 문장 생성에만 사용하는 허용목록 기반 입력."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = PROPERTY_REPORT_AI_INPUT_SCHEMA_VERSION
    as_of: date
    criteria: PropertySearchCriteria
    handoff: PropertyAffordabilityAIHandoff
    financial_diagnosis: PropertyReportDiagnosis
    generation_rules: tuple[str, ...] = (
        "제공된 금액·비율·상품명·판정을 변경하거나 다시 계산하지 않습니다.",
        "매물별 결과를 서로 섞지 않습니다. 한 매물의 값을 다른 매물에 붙이지 않습니다.",
        "UNKNOWN과 UNSUPPORTED는 구매 가능 판정이 아닙니다.",
        "누락된 입력을 해결된 것처럼 서술하지 않습니다.",
        "대출 승인, 상품 가입 또는 미래 가격을 보장하지 않습니다.",
        "조달 후보에 포함된 대출 상품만 언급합니다.",
    )

    @property
    def missing_inputs(self) -> tuple[str, ...]:
        """핸드오프와 현금흐름 진단의 결측을 순서대로 합친다."""
        return tuple(
            dict.fromkeys(
                self.handoff.missing_inputs + self.financial_diagnosis.missing_inputs
            )
        )

    @property
    def policy_sources(self) -> tuple[str, ...]:
        return self.handoff.policy_sources

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "PROPERTY_REPORT_AI_INPUT_SCHEMA_VERSION",
    "PropertyReportAIInput",
    "PropertyReportDiagnosis",
]
