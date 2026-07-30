"""API·프론트엔드·보고서가 함께 사용하는 버전형 시뮬레이션 계약.

목적:
    계산 엔진의 dataclass를 직접 외부에 노출하지 않고 손실 없는 JSON 경계를
    제공한다. 엔진 계산식과 외부 표현 형식을 분리해 어느 한쪽의 변경이 다른
    계층을 불필요하게 깨뜨리지 않게 한다.
기능:
    주택구매·전세·월세보증금 목표 입력, 개인정보를 제외한 사용자 요약,
    엔진별 실행 여부와 원본 결과를 포함한 최상위 ``SimulationResult``를 정의한다.
근거:
    공식 설계안의 API 공통 계약과 보고서 생성 흐름을 따르며, 금액 정밀도와
    UNKNOWN 의미를 보존하기 위해 ``Decimal``과 ``None``을 유지한다.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SIMULATION_RESULT_SCHEMA_VERSION = "1.0.0"
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


class GoalType(StrEnum):
    HOME_PURCHASE = "HOME_PURCHASE"
    JEONSE_DEPOSIT = "JEONSE_DEPOSIT"
    MONTHLY_RENT_DEPOSIT = "MONTHLY_RENT_DEPOSIT"


class SectionRunStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NOT_RUN = "NOT_RUN"


class UserProfile(BaseModel):
    """계산에 필요한 사용자 사실.

    ``persona_name``은 테스트 페르소나 라벨이며 실명 필드가 아니다. 주민번호,
    계좌번호와 거래내역은 이 공용 계약의 입력으로 받지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    persona_name: str | None = None
    age: int = Field(ge=19, le=120)
    household_size: int = Field(default=1, ge=1)
    annual_income: Decimal = Field(ge=0)
    employment_type: str | None = None
    is_first_home_buyer: bool = False
    is_married: bool = False
    region_code: str | None = None


class HousingGoal(BaseModel):
    """목표 유형과 금액.

    ``target_price``는 초기 API와의 호환 필드다. 신규 호출자는 목표 종류와
    무관하게 ``target_amount``를 사용한다. 두 값이 함께 오면 반드시 같아야 한다.
    """

    model_config = ConfigDict(extra="forbid")

    goal_type: GoalType = GoalType.HOME_PURCHASE
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_price: Decimal | None = Field(default=None, gt=0)
    target_date: date
    region_code: str | None = None
    monthly_rent: Decimal | None = Field(default=None, ge=0)
    management_fee: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_target_amount(self) -> "HousingGoal":
        if self.target_amount is None and self.target_price is None:
            raise ValueError("target_amount 또는 target_price 중 하나는 필요합니다.")
        if (
            self.target_amount is not None
            and self.target_price is not None
            and self.target_amount != self.target_price
        ):
            raise ValueError("target_amount와 target_price가 서로 다릅니다.")
        if self.goal_type is GoalType.MONTHLY_RENT_DEPOSIT and self.monthly_rent is None:
            raise ValueError("월세보증금 목표에는 monthly_rent가 필요합니다.")
        return self

    @property
    def resolved_target_amount(self) -> Decimal:
        amount = self.target_amount if self.target_amount is not None else self.target_price
        # 위 model_validator가 None을 차단한다. 타입 검사기에도 불변조건을 명시한다.
        if amount is None:  # pragma: no cover - 방어적 분기
            raise RuntimeError("목표금액이 검증되지 않았습니다.")
        return amount


class FinancialSnapshot(BaseModel):
    """계산 기준일의 집계 금융정보.

    ``monthly_expense``는 기존 대출 월 상환액을 제외한 생활비이며,
    ``monthly_debt_payment``에서 부채상환을 별도로 받는다. ``emergency_reserve``는
    ``liquid_assets``에 포함된 금액 중 비상용으로 지정한 현재 잔액이므로 별도
    자산처럼 더하지 않는다. ``None``은 0원이 아니라 현재 비상자금 미확정을 뜻한다.
    """

    model_config = ConfigDict(extra="forbid")

    monthly_income: Decimal = Field(ge=0)
    monthly_expense: Decimal = Field(ge=0)
    liquid_assets: Decimal = Field(ge=0)
    housing_assets: Decimal = Field(default=Decimal(0), ge=0)
    total_debt: Decimal = Field(default=Decimal(0), ge=0)
    monthly_debt_payment: Decimal = Field(default=Decimal(0), ge=0)
    emergency_reserve: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_emergency_reserve_is_liquid(self) -> "FinancialSnapshot":
        if self.emergency_reserve is not None and self.emergency_reserve > self.liquid_assets:
            raise ValueError("emergency_reserve는 liquid_assets를 초과할 수 없습니다.")
        return self


class SimulationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: UserProfile
    housing_goal: HousingGoal
    financial_snapshot: FinancialSnapshot


class PublicUserSummary(BaseModel):
    """보고서에 전달할 수 있는 개인정보 최소화 사용자 요약."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_name: str | None = None
    age: int
    household_size: int
    annual_income: Decimal
    employment_type: str | None = None
    is_first_home_buyer: bool
    is_married: bool
    region_code: str | None = None
    monthly_income: Decimal
    monthly_expense: Decimal
    liquid_assets: Decimal
    housing_assets: Decimal
    total_debt: Decimal
    monthly_debt_payment: Decimal
    emergency_reserve: Decimal | None = None


class HousingGoalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_type: GoalType
    target_amount: Decimal
    target_date: date
    region_code: str | None = None
    monthly_rent: Decimal | None = None
    management_fee: Decimal | None = None


class CalculationSection(BaseModel):
    """엔진 하나의 실행 상태와 손실 없는 JSON 결과.

    ``result``는 조립 서비스가 dataclass의 모든 필드를 JSON 값으로 변환한 원본이다.
    외부 소비자는 ``section_schema_version``을 확인한 뒤 필드를 사용한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_status: SectionRunStatus
    section_schema_version: str
    engine_status: str | None
    result: dict[str, JsonValue] | None
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_run_state(self) -> "CalculationSection":
        if self.run_status is SectionRunStatus.COMPLETED and self.result is None:
            raise ValueError("COMPLETED 계산 구간에는 result가 필요합니다.")
        if self.run_status is SectionRunStatus.NOT_RUN and self.result is not None:
            raise ValueError("NOT_RUN 계산 구간에는 result를 넣을 수 없습니다.")
        return self


class SimulationResult(BaseModel):
    """전체 계산의 단일 원본(source of truth) JSON 계약."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SIMULATION_RESULT_SCHEMA_VERSION
    simulation_id: UUID
    as_of: date
    calculated_at: datetime
    user_summary: PublicUserSummary
    goal: HousingGoalSummary
    cashflow: CalculationSection
    savings_portfolio: CalculationSection
    loan_simulation: CalculationSection
    recommendation: CalculationSection
    stress_test: CalculationSection
    strategy_comparison: CalculationSection
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_calculated_at_timezone(self) -> "SimulationResult":
        if self.calculated_at.tzinfo is None or self.calculated_at.utcoffset() is None:
            raise ValueError("calculated_at은 시간대가 포함된 datetime이어야 합니다.")
        return self

    def to_json_dict(self) -> dict[str, Any]:
        """금액은 문자열, 날짜는 ISO 형식, 미확정값은 null인 JSON 준비 사전."""

        return self.model_dump(mode="json")


# 초기 코드가 참조하던 얇은 요약 계약은 호환을 위해 남긴다. 신규 코드에서는
# CalculationSection과 SimulationResult의 상세 결과를 사용한다.
class EngineSummary(BaseModel):
    status: str
    score: Decimal | None = None
    reasons: list[str] = Field(default_factory=list)
