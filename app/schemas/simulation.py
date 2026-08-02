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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# LTV 표와 같은 어휘를 쓰려고 규제 모듈의 enum을 그대로 재사용한다. 여기서
# 별도 목록을 만들면 API와 규제표가 갈라져 같은 차주에게 다른 한도가 나온다.
from app.regulations.mortgage_limits import HousingStatus

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
    # DSR 분모. **금융사 인정소득**이며 거래내역에서 집계한 실수령 소득과 다르다
    # (`mydata_design.md` §9). 없으면 월소득 × 12로 파생하고 그 사실을 가정으로
    # 남긴다 — 파생값은 세후 실수령 기준이라 인정소득보다 작고, 소득이 작으면
    # DSR이 커져 **한도가 작게** 나온다. 과소평가는 안전한 방향이다(§22.3).
    annual_income: Decimal | None = Field(default=None, ge=0)
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


class LoanRequestInput(BaseModel):
    """대출 계산에 필요하지만 사용자 요약만으로는 확정할 수 없는 사실.

    이 블록이 없으면 대출 이후 구간(대출·종합추천·스트레스·전략)을 실행하지 않고
    ``NOT_RUN``으로 남긴다. 기본값으로 채우지 않는 이유는 여기 값들이 전부
    **틀리면 한도가 커지는 축**이기 때문이다.

    - ``housing_status``: ``UserProfile.is_first_home_buyer``만으로는 1주택 미처분과
      다주택을 가릴 수 없는데, LTV는 그 사이에서 0%와 80%로 갈린다.
      규제표와 같은 어휘를 쓰려고 ``HousingStatus``를 그대로 재사용한다.
    - ``months``: 만기가 없으면 PMT도 DTI 원금 역산도 성립하지 않는다.
    - ``monthly_essential_expense``: 총지출이 아니라 필수생활비다. Buffer(부록 A-8)
      기준이 여기서 나오므로 ``FinancialSnapshot.monthly_expense``로 대체할 수 없다.
    """

    model_config = ConfigDict(extra="forbid")

    months: int = Field(gt=0, le=600)
    housing_status: HousingStatus
    monthly_essential_expense: Decimal = Field(ge=0)
    # 없으면 목표금액 − 유동자산으로 파생하고 가정을 남긴다. 취득세·부대비용이
    # 빠지므로 필요금액을 과소평가하는데, 필요금액은 대출 상한 중 하나라서
    # (`loan_max`의 `hi = min(ltv, product, dti, required)`) 과소평가가 안전한 쪽이다.
    required_amount: Decimal | None = Field(default=None, ge=0)
    # DSR 분자(원리금). 없으면 월 상환액 × 12로 파생한다.
    existing_annual_debt_service: Decimal | None = Field(default=None, ge=0)
    # DTI 분자(이자만). 없으면 어댑터가 DSR용 값으로 물러서 DTI를 낮게 잡는다.
    existing_annual_interest: Decimal | None = Field(default=None, ge=0)
    post_purchase_monthly_income: Decimal | None = Field(default=None, ge=0)
    post_purchase_monthly_expense: Decimal | None = Field(default=None, ge=0)
    # 법정 상한이 아니라 서비스 내부 안전기준이다(SSOT §14.1). 40%는 SSOT가
    # "그대로 둔다"고 확정한 값이라 기본값으로 쓴다. 결과에는 내부 기준으로 표기한다.
    safe_dsr: Decimal = Field(default=Decimal("0.40"), gt=0, le=1)
    rate_selection: Literal["avg", "min", "max"] = "avg"
    # 잔액 1억원 초과에만 스트레스 금리가 붙으므로, 모르면 신용대출을 계산하지
    # 않고 결측으로 남긴다. 0으로 채우면 한도가 과대평가된다.
    credit_loan_balance: Decimal | None = Field(default=None, ge=0)
    # 적용할 규제의 기준일. 경과규정 대상 차주는 신청 접수 시점을 넘긴다.
    # 없으면 계산 기준일(``as_of``)을 쓴다.
    regulation_as_of: date | None = None
    for_house_purchase: bool = True
    # 상품명 → 고객이 실제로 부담하는 부대비용 총액(보증료·인지세·채권매입 손실 등).
    #
    # 왜 사용자 입력인가: 원천 데이터의 부대비용 원문에 국민주택채권 매입·할인
    # 비용이 들어 있는데, 할인율이 채권 시세로 매일 변해 우리가 확정할 수 없다.
    # 검수표로 닫히지 않는 종류의 값이며, 은행이 실행 직전에 안내한다.
    #
    # 넣지 않으면 §14.2 총비용 점수가 산출되지 않고 부록 A-10이 가중치를
    # 재정규화한다. **일부 상품만 넣어도 마찬가지다** — 항목이 상품마다 다르게
    # 빠지면 비용을 빠뜨린 상품이 유리해져 순위가 뒤집힌다.
    #
    # 은행 부담 항목은 넣지 않는다. 여기 값은 차주가 내는 금액이다.
    loan_incidental_costs: dict[str, Decimal] | None = None

    @model_validator(mode="after")
    def validate_incidental_costs(self) -> "LoanRequestInput":
        for name, amount in (self.loan_incidental_costs or {}).items():
            if not name.strip():
                raise ValueError("부대비용 항목의 상품명은 비어 있을 수 없습니다.")
            if amount < 0:
                raise ValueError(f"{name}의 부대비용은 음수일 수 없습니다.")
        return self


class SavingsRequestInput(BaseModel):
    """예·적금 계산에 필요하지만 사용자 요약만으로는 확정할 수 없는 사실.

    이 블록이 없으면 예·적금 구간을 실행하지 않고 ``NOT_RUN``으로 남긴다.
    ``LoanRequestInput``과 같은 규약이지만 **보수적인 방향이 반대**다. 대출은
    모르면 한도가 커지는 쪽이 위험하고, 예·적금은 모르면 수익이 커지는 쪽이
    위험하다. 그래서 기본값은 전부 수익을 낮추는 쪽으로 둔다.

    예산 두 값은 현금흐름 진단에서 파생할 수 있어 선택이다. 나머지 취향값은
    파생할 수 없으므로, 없으면 결측으로 남기고 문서에 가정으로 적는다.
    """

    model_config = ConfigDict(extra="forbid")

    # 없으면 ``HousingGoal.target_date``를 쓴다. 만기가 이 날짜를 넘는 상품은
    # 돈이 필요한 시점에 묶여 있으므로 평가 단계가 만기위험으로 반영한다.
    fund_needed_date: date | None = None
    # 없으면 현금흐름 진단의 월 주택저축 가능액을 쓴다.
    monthly_savings_budget: Decimal | None = Field(default=None, ge=0)
    # 없으면 비상자금 목표를 뺀 사용 가능 유동자산을 쓴다.
    lump_sum_budget: Decimal | None = Field(default=None, ge=0)
    # 우대금리 달성 확률. **기본값 0이다** — 우대조건 달성 여부는 자유텍스트
    # 자격조건이라 우리가 판정하지 않는다(부록 B-3). 달성한다고 보면 만기액이
    # 커지므로, 모를 때는 미달성으로 둔다.
    bonus_achievement_probability: Decimal = Field(default=Decimal(0), ge=0, le=1)
    # 말일 납입이 이자를 적게 준다. 모를 때 초일 납입으로 두면 수익 과대평가다.
    contribution_timing: Literal["beginning", "end"] = "end"
    # **허용 일수가 아니라 점수 감쇠 척도다.** 만기가 필요 시점에서 이만큼
    # 어긋나면 만기적합 점수를 1/e로 본다(`evaluation._maturity_fit_score`).
    # 만기가 필요 시점을 넘으면 부적격이라는 판정은 이 값과 무관하게 항상 걸린다.
    # 0은 척도로 성립하지 않으므로 허용하지 않는다. 기본 30일은 공식 설계안이
    # 정하지 않은 서비스 내부 값이며 순위에만 영향을 준다.
    maturity_tolerance_days: int = Field(default=30, gt=0)
    # 유동성 선호. 순위에만 쓰이고 제약은 아니다. 없으면 현금흐름 엔진이
    # 미확인 위험에 쓰는 것과 같은 정책 중립값을 쓰고 결측으로 기록한다.
    liquidity_preference: Literal["low", "medium", "high"] | None = None
    accepts_principal_risk: bool = False
    # 금융회사 코드 → 이미 예치한 금액. 예금자보호 한도를 회사 단위로 계산한다.
    # 비어 있으면 "기존 예치금이 없다"가 아니라 "확인되지 않았다"로 기록한다.
    existing_institution_deposits: dict[str, Decimal] = Field(default_factory=dict)
    # 상한 3은 엔진의 MVP 제약이다(조합 폭증 방지, `SavingsPortfolioPolicy`).
    maximum_recommended_products: int = Field(default=3, gt=0, le=3)
    # Rule Pack이 보는 자격 사실. 없으면 해당 규칙이 UNKNOWN으로 남는다.
    applicant_type: str | None = None
    is_first_payment: bool | None = None

    @field_validator("existing_institution_deposits")
    @classmethod
    def validate_existing_deposits(
        cls,
        value: dict[str, Decimal],
    ) -> dict[str, Decimal]:
        for code, amount in value.items():
            if not code.strip():
                raise ValueError("금융회사 코드는 비어 있을 수 없습니다.")
            if amount < 0:
                raise ValueError("기존 예치액은 음수일 수 없습니다.")
        return value


class AcquisitionCostInput(BaseModel):
    """총 구매비용(§8.2)을 확정하는 데 필요한 법적 사실.

    이 블록이 없으면 시나리오별 목표 주택가격을 만들지 않는다. 매매가만으로
    시나리오를 세우면 취득세·중개보수가 빠져 **필요 자금을 실제보다 작게** 잡고,
    그러면 계획이 실제보다 쉬워 보인다.

    매물 흐름의 ``PropertyAcquisitionProfileInput``과 필드가 겹치지만 축이 다르다 —
    저쪽은 매물마다 덮어쓰는 표이고 이쪽은 목표 하나에 붙는 값이다. 둘 다 같은
    엔진(``purchase_costs``)에 들어가며 필드의 뜻은 그 엔진이 정한다.
    """

    model_config = ConfigDict(extra="forbid")

    buyer_is_corporation: bool | None = None
    household_home_count_after_purchase: int | None = Field(default=None, gt=0)
    is_registered_housing: bool | None = None
    is_luxury_home: bool | None = None
    exclusive_area_m2: Decimal | None = Field(default=None, gt=0)
    is_national_housing_scale_override: bool | None = None
    registration_and_legal_costs: Decimal | None = Field(default=None, ge=0)
    brokerage_vat_rate_override: Decimal | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_housing_classification(self) -> "AcquisitionCostInput":
        if self.is_registered_housing is False and (
            self.is_national_housing_scale_override is True
        ):
            raise ValueError("주택이 아닌 물건을 국민주택규모로 표시할 수 없습니다.")
        return self


# 연소득을 월소득에서 파생했을 때 결과에 남기는 문구. 숫자만 내보내면 근거 없는
# 확언이 된다(§20).
DERIVED_ANNUAL_INCOME_NOTE = (
    "연소득을 월소득 × 12로 파생했습니다. DSR 심사는 금융사 인정소득으로 하며 "
    "그 값은 보통 세후 실수령액보다 큽니다. 따라서 실제 한도는 여기 계산보다 "
    "클 수 있습니다."
)


class AnnualIncomeSource(StrEnum):
    """연소득이 어디서 왔는지. 결과를 읽는 쪽이 가정 여부를 알아야 한다."""

    PROVIDED = "PROVIDED"
    DERIVED_FROM_MONTHLY = "DERIVED_FROM_MONTHLY"


class ResolvesAnnualIncome:
    """``profile``과 ``financial_snapshot``을 함께 가진 입력이 공유하는 규칙.

    ``/simulations``와 ``/properties/affordability``가 같은 값을 다르게 계산하면
    같은 차주에게 두 화면이 다른 한도를 보여준다.
    """

    profile: UserProfile
    financial_snapshot: FinancialSnapshot

    @property
    def annual_income_source(self) -> AnnualIncomeSource:
        if self.profile.annual_income is None:
            return AnnualIncomeSource.DERIVED_FROM_MONTHLY
        return AnnualIncomeSource.PROVIDED

    @property
    def resolved_annual_income(self) -> Decimal:
        """DSR 분모로 쓸 연소득. 없으면 월소득 × 12로 파생한다.

        **파생값은 인정소득보다 작다.** 마이데이터가 주는 월소득은 세후 실수령이고
        인정소득은 보통 세전 기준이라, 12를 곱해도 인정소득에 못 미친다. 소득이
        작으면 DSR이 커져 한도가 작게 나오므로 방향은 안전하다.

        정확히 하려면 인정소득을 따로 받아야 한다(`mydata_design.md` §9가
        "합의 필요"로 표시해 둔 항목이다). 그 전까지 이 파생을 쓰고, 쓴 사실을
        ``DERIVED_ANNUAL_INCOME_NOTE``로 결과에 남긴다.
        """
        if self.profile.annual_income is not None:
            return self.profile.annual_income
        return self.financial_snapshot.monthly_income * Decimal(12)


class SimulationInput(BaseModel, ResolvesAnnualIncome):
    model_config = ConfigDict(extra="forbid")

    profile: UserProfile
    housing_goal: HousingGoal
    financial_snapshot: FinancialSnapshot
    loan_request: LoanRequestInput | None = None
    savings_request: SavingsRequestInput | None = None
    acquisition_costs: AcquisitionCostInput | None = None


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
    # 여러 대출을 동시에 실행하는 조합안. `loan_simulation`이 옵션 **하나**의
    # 한도라면 이쪽은 그것들을 공유 예산(DSR·현금흐름·LTV) 안에서 묶은 결과다.
    # 두 절의 금액을 더하면 안 된다 — 조합 절이 이미 합계를 담고 있다.
    #
    # 하위 호환 추가라 최상위 `schema_version`은 올리지 않는다(README 「변경
    # 원칙」). 이 구간을 소비하는 쪽은 `section_schema_version`을 본다.
    loan_combination: CalculationSection
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
