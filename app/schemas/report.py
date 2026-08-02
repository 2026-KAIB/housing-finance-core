"""결과 보고서 AI에 허용할 최소 JSON 계약.

AI는 이 계약의 숫자·상품명·상태를 설명할 수만 있고 재계산하거나 변경할 수 없다.
원천 마이데이터, 계좌번호와 거래내역은 이 계약에 존재하지 않는다.
"""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.simulation import (
    GoalType,
    HousingGoalSummary,
    JsonValue,
    PublicUserSummary,
    SectionRunStatus,
)

REPORT_AI_INPUT_SCHEMA_VERSION = "1.0.0"


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_status: SectionRunStatus
    engine_status: str | None
    facts: dict[str, JsonValue] | None
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    # 값을 확정하지 못해 **무엇으로 대신 채웠는지**. `reasons`(왜 이런 판정이
    # 나왔는지)와 섞지 않는다. 이 칸이 없던 동안 보고서 양식은 `reasons`에서
    # "가정"·"파생" 같은 낱말을 찾아 가정을 추려냈는데, 가정은 애초에 여기 오는
    # 값이라 한 건도 걸리지 않았다 — 필요 대출금액이 부대비용을 빼고 계산됐다는
    # 경고가 그렇게 문서에서 사라졌다.
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()


class ReportSections(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    financial_diagnosis: ReportSection
    savings: ReportSection
    loan: ReportSection
    recommendation: ReportSection
    stress_test: ReportSection
    strategy_comparison: ReportSection


class ReportAIInput(BaseModel):
    """AI가 보고서 문장 생성에만 사용하는 허용목록 기반 입력."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = REPORT_AI_INPUT_SCHEMA_VERSION
    source_schema_version: str
    simulation_id: UUID
    as_of: date
    user_summary: PublicUserSummary
    goal: HousingGoalSummary
    sections: ReportSections
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()
    generation_rules: tuple[str, ...] = (
        "제공된 금액·비율·점수·상품명·상태를 변경하거나 다시 계산하지 않습니다.",
        "null과 UNKNOWN은 실패나 0으로 해석하지 않습니다.",
        "대출 승인, 상품 가입 또는 미래 가격을 보장하지 않습니다.",
        "대출·예적금 상품은 종합추천 결과에 포함된 후보만 추천합니다.",
        "추천 이유·위험·확인할 항목을 계산 결과의 근거 안에서만 설명합니다.",
    )

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "GoalType",
    "REPORT_AI_INPUT_SCHEMA_VERSION",
    "ReportAIInput",
    "ReportSection",
    "ReportSections",
]
