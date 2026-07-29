"""금리·소득·생활비 스트레스 테스트의 계층 간 불변 계약.

목적:
    규제 심사용 스트레스 DSR과 사용자의 생활 안정성 시나리오를 분리한다.
    이 계약의 금리 충격은 실제 월 상환액 변화 가정이며 법정 심사 가산금리가 아니다.
기능:
    명시적인 충격 시나리오, 추천된 대출·저축 계획과 차주 현금흐름 입력,
    시나리오별 DSR·Buffer·적금 유지 결과를 정의한다.
근거:
    공식 설계안 §17.1~17.5의 금리 상승, 소득 감소, 생활비 증가, 복합 충격 공식과
    §14.3의 구매 후 월 잉여자금 기준을 따른다. 충격 크기는 공식 수치가 아니므로
    ``StressScenario`` 목록에 노출해 서비스 내부 가정임을 명시한다.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class StressScenarioKind(StrEnum):
    BASELINE = "BASELINE"
    INTEREST_RATE = "INTEREST_RATE"
    INCOME = "INCOME"
    LIVING_EXPENSE = "LIVING_EXPENSE"
    COMBINED = "COMBINED"


class InterestRateShockApplicability(StrEnum):
    """추천대출의 실제 상환액에 금리 충격을 적용할 수 있는지."""

    APPLIES = "APPLIES"
    NOT_APPLIES = "NOT_APPLIES"
    UNKNOWN = "UNKNOWN"


class StressScenarioStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class StressCheck(StrEnum):
    SAFE_DSR = "SAFE_DSR"
    CASH_BUFFER = "CASH_BUFFER"
    SAVINGS_PLAN = "SAVINGS_PLAN"


@dataclass(frozen=True)
class StressScenario:
    """비율 입력 계약.

    ``interest_rate_increase``는 퍼센트 숫자가 아니라 비율이다.
    예: 1.0%p 상승은 ``Decimal("0.01")``이다.
    """

    code: str
    name: str
    kind: StressScenarioKind
    interest_rate_increase: Decimal = Decimal(0)
    income_reduction_ratio: Decimal = Decimal(0)
    living_expense_increase_ratio: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.name.strip():
            raise ValueError("시나리오 코드와 이름은 비어 있을 수 없습니다.")
        if self.interest_rate_increase < 0:
            raise ValueError("interest_rate_increase은(는) 음수일 수 없습니다.")
        if not Decimal(0) <= self.income_reduction_ratio < Decimal(1):
            raise ValueError("income_reduction_ratio은(는) 0 이상 1 미만이어야 합니다.")
        if self.living_expense_increase_ratio < 0:
            raise ValueError("living_expense_increase_ratio은(는) 음수일 수 없습니다.")
        has_rate = self.interest_rate_increase > 0
        has_income = self.income_reduction_ratio > 0
        has_expense = self.living_expense_increase_ratio > 0
        shock_count = sum((has_rate, has_income, has_expense))
        expected_kind = (
            StressScenarioKind.BASELINE
            if shock_count == 0
            else (
                StressScenarioKind.COMBINED
                if shock_count > 1
                else (
                    StressScenarioKind.INTEREST_RATE
                    if has_rate
                    else (
                        StressScenarioKind.INCOME
                        if has_income
                        else StressScenarioKind.LIVING_EXPENSE
                    )
                )
            )
        )
        if self.kind is not expected_kind:
            raise ValueError(
                f"시나리오 충격값과 kind가 일치하지 않습니다: "
                f"expected={expected_kind}, actual={self.kind}"
            )


# 공식 설계안은 충격 종류만 정하고 크기는 정하지 않는다. 아래 값은 발표와 회귀
# 테스트에 쓰는 MVP 내부 시나리오이며 API 호출자가 다른 목록으로 교체할 수 있다.
DEFAULT_STRESS_SCENARIOS = (
    StressScenario(
        code="BASELINE",
        name="현재 조건",
        kind=StressScenarioKind.BASELINE,
    ),
    StressScenario(
        code="RATE_UP_0_5P",
        name="금리 0.5%p 상승",
        kind=StressScenarioKind.INTEREST_RATE,
        interest_rate_increase=Decimal("0.005"),
    ),
    StressScenario(
        code="RATE_UP_1_0P",
        name="금리 1.0%p 상승",
        kind=StressScenarioKind.INTEREST_RATE,
        interest_rate_increase=Decimal("0.010"),
    ),
    StressScenario(
        code="RATE_UP_2_0P",
        name="금리 2.0%p 상승",
        kind=StressScenarioKind.INTEREST_RATE,
        interest_rate_increase=Decimal("0.020"),
    ),
    StressScenario(
        code="INCOME_DOWN_10",
        name="소득 10% 감소",
        kind=StressScenarioKind.INCOME,
        income_reduction_ratio=Decimal("0.10"),
    ),
    StressScenario(
        code="INCOME_DOWN_20",
        name="소득 20% 감소",
        kind=StressScenarioKind.INCOME,
        income_reduction_ratio=Decimal("0.20"),
    ),
    StressScenario(
        code="EXPENSE_UP_10",
        name="생활비 10% 증가",
        kind=StressScenarioKind.LIVING_EXPENSE,
        living_expense_increase_ratio=Decimal("0.10"),
    ),
    StressScenario(
        code="EXPENSE_UP_20",
        name="생활비 20% 증가",
        kind=StressScenarioKind.LIVING_EXPENSE,
        living_expense_increase_ratio=Decimal("0.20"),
    ),
    StressScenario(
        code="COMBINED_SEVERE",
        name="금리 2.0%p·소득 20% 감소·생활비 20% 증가",
        kind=StressScenarioKind.COMBINED,
        interest_rate_increase=Decimal("0.020"),
        income_reduction_ratio=Decimal("0.20"),
        living_expense_increase_ratio=Decimal("0.20"),
    ),
)


@dataclass(frozen=True)
class StressTestInput:
    """추천된 계획을 스트레스하는 완전한 입력.

    기존 대출의 금리 재산정 정보는 현재 MyData에 없으므로
    ``other_existing_monthly_debt_service``와
    ``existing_annual_debt_service``는 고정한다. 금리 충격은 추천된 신규 대출에만
    적용하며 이 범위를 ``scope_notes``에 남긴다.
    """

    as_of: date
    loan_principal: Decimal
    annual_rate: Decimal
    months: int
    annual_income: Decimal
    existing_annual_debt_service: Decimal
    post_purchase_monthly_income: Decimal
    post_purchase_monthly_expense: Decimal
    other_existing_monthly_debt_service: Decimal
    monthly_essential_expense: Decimal
    safe_dsr: Decimal
    monthly_savings_commitment: Decimal | None
    interest_rate_shock_applicability: InterestRateShockApplicability
    scenarios: tuple[StressScenario, ...] = DEFAULT_STRESS_SCENARIOS
    precondition_missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    scope_notes: tuple[str, ...] = (
        "금리 충격은 추천된 신규 대출에만 적용하며 기존 대출 상환액은 고정합니다.",
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("loan_principal", self.loan_principal),
            ("annual_rate", self.annual_rate),
            ("existing_annual_debt_service", self.existing_annual_debt_service),
            ("post_purchase_monthly_income", self.post_purchase_monthly_income),
            ("post_purchase_monthly_expense", self.post_purchase_monthly_expense),
            (
                "other_existing_monthly_debt_service",
                self.other_existing_monthly_debt_service,
            ),
            ("monthly_essential_expense", self.monthly_essential_expense),
            ("safe_dsr", self.safe_dsr),
        ):
            if value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")
        if self.annual_income <= 0:
            raise ValueError("annual_income은(는) 0보다 커야 합니다.")
        if self.months <= 0:
            raise ValueError("months은(는) 0보다 커야 합니다.")
        if self.loan_principal > 0 and self.safe_dsr <= 0:
            raise ValueError("대출원금이 있으면 safe_dsr은(는) 0보다 커야 합니다.")
        if self.monthly_savings_commitment is not None and self.monthly_savings_commitment < 0:
            raise ValueError("monthly_savings_commitment은(는) 음수일 수 없습니다.")
        if not self.scenarios:
            raise ValueError("스트레스 시나리오는 하나 이상이어야 합니다.")
        scenario_codes = [scenario.code for scenario in self.scenarios]
        if len(scenario_codes) != len(set(scenario_codes)):
            raise ValueError("스트레스 시나리오 code는 중복될 수 없습니다.")
        if not any(scenario.kind is StressScenarioKind.BASELINE for scenario in self.scenarios):
            raise ValueError("기준(BASELINE) 시나리오가 필요합니다.")


@dataclass(frozen=True)
class StressScenarioResult:
    scenario: StressScenario
    status: StressScenarioStatus
    applied_annual_rate: Decimal | None
    stressed_annual_income: Decimal
    stressed_monthly_income: Decimal
    stressed_monthly_expense: Decimal
    stressed_monthly_essential_expense: Decimal
    monthly_payment: Decimal | None
    monthly_payment_increase: Decimal | None
    expected_dsr: Decimal | None
    safe_dsr: Decimal
    cashflow_before_savings: Decimal | None
    buffer_target: Decimal
    buffer_margin: Decimal | None
    monthly_savings_commitment: Decimal | None
    sustainable_monthly_savings: Decimal | None
    savings_shortfall: Decimal | None
    cashflow_after_savings: Decimal | None
    dsr_within_limit: bool | None
    buffer_maintained: bool | None
    savings_plan_maintainable: bool | None
    failed_checks: tuple[StressCheck, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StressTestResult:
    status: StressScenarioStatus
    as_of: date
    scenarios: tuple[StressScenarioResult, ...]
    pass_count: int
    fail_count: int
    unknown_count: int
    pass_ratio: Decimal
    first_failed_scenario: str | None
    maximum_dsr: Decimal | None
    minimum_buffer_margin: Decimal | None
    maximum_savings_shortfall: Decimal | None
    scope_notes: tuple[str, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)
