"""자산축적형·조기구매형 전략 비교의 계층 간 불변 계약.

목적:
    검증된 종합추천과 스트레스 결과를 두 구매전략의 비교 입력으로 바꾸되,
    미래 주택가격·미래 대출한도·미개발 현금흐름 값을 임의로 만들지 않는다.
기능:
    주택가격 시나리오, 전략별 가용 자기자본·대출계획, 공식 전략점수의
    구성요소와 비교 결과를 ``Decimal`` 기반 dataclass로 정의한다.
근거:
    공식 설계안 §15의 자산축적형·조기구매형 산출물과 §16의 전략점수,
    시나리오 커버리지 공식을 따른다. 공식 문서가 정하지 않은 점수 완성도와
    동점 허용치는 ``StrategyPolicy``에 노출해 교체 가능하게 한다.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class StrategyKind(StrEnum):
    ASSET_ACCUMULATION = "ASSET_ACCUMULATION"
    EARLY_PURCHASE = "EARLY_PURCHASE"


class StrategyScenarioStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class StrategyScoreStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PROVISIONAL = "PROVISIONAL"
    UNAVAILABLE = "UNAVAILABLE"


class StrategyComparisonStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PROVISIONAL = "PROVISIONAL"
    INFEASIBLE = "INFEASIBLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class StrategyPolicy:
    """공식 전략점수 가중치와 서비스 내부 비교 기준."""

    scenario_attainment_weight: Decimal = Decimal("0.35")
    cashflow_stability_weight: Decimal = Decimal("0.25")
    total_financial_cost_weight: Decimal = Decimal("0.20")
    goal_timing_weight: Decimal = Decimal("0.10")
    plan_flexibility_weight: Decimal = Decimal("0.10")
    minimum_score_completeness: Decimal = Decimal("0.60")
    score_tie_tolerance: Decimal = Decimal("0.01")
    policy_note: str = (
        "전략점수 가중치는 공식 설계안 §16을 따릅니다. 결측값은 0점으로 "
        "대체하지 않고 확인된 가중치 안에서만 임시 점수를 계산합니다."
    )

    def __post_init__(self) -> None:
        for name, value in self.weights.items():
            if value < 0 or value > 1:
                raise ValueError(f"{name}은(는) 0 이상 1 이하이어야 합니다.")
        if sum(self.weights.values(), Decimal(0)) != Decimal(1):
            raise ValueError("전략점수 가중치 합은 1이어야 합니다.")
        if not Decimal(0) <= self.minimum_score_completeness <= Decimal(1):
            raise ValueError("minimum_score_completeness은(는) 0 이상 1 이하이어야 합니다.")
        if self.score_tie_tolerance < 0:
            raise ValueError("score_tie_tolerance은(는) 음수일 수 없습니다.")
        if not self.policy_note.strip():
            raise ValueError("policy_note은(는) 비어 있을 수 없습니다.")

    @property
    def weights(self) -> dict[str, Decimal]:
        return {
            "scenario_attainment": self.scenario_attainment_weight,
            "cashflow_stability": self.cashflow_stability_weight,
            "total_financial_cost": self.total_financial_cost_weight,
            "goal_timing": self.goal_timing_weight,
            "plan_flexibility": self.plan_flexibility_weight,
        }


DEFAULT_STRATEGY_POLICY = StrategyPolicy()


@dataclass(frozen=True)
class HousingCostScenario:
    """구매시점 차이를 반영한 호출자 제공 주택 총구매비용 시나리오.

    두 가격은 매매가뿐 아니라 취득 관련 비용까지 포함한 같은 범위의 금액이어야
    한다. 엔진은 미래 가격을 예측하지 않고 전달받은 값을 그대로 사용한다.
    """

    code: str
    name: str
    early_purchase_total_cost: Decimal
    asset_accumulation_total_cost: Decimal
    is_baseline: bool = False
    basis_date: date | None = None
    source_note: str = "호출자 제공 주택가격 시나리오"
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.name.strip():
            raise ValueError("주택가격 시나리오 코드와 이름은 비어 있을 수 없습니다.")
        for name, value in (
            ("early_purchase_total_cost", self.early_purchase_total_cost),
            ("asset_accumulation_total_cost", self.asset_accumulation_total_cost),
        ):
            if value <= 0:
                raise ValueError(f"{name}은(는) 0보다 커야 합니다.")
        if not self.source_note.strip():
            raise ValueError("source_note은(는) 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class StrategyCandidateInput:
    """한 전략의 확인된 계획값.

    ``available_equity``는 해당 전략의 구매시점에 실제 사용할 자기자본이다.
    ``loan_capacity``는 승인 보장이 아니라 앞 계산 또는 명시적 미래 가정으로
    확보된 계획 한도다. 모르는 값은 반드시 ``None``으로 둔다.
    """

    kind: StrategyKind
    planned_purchase_date: date | None
    available_equity: Decimal | None
    loan_capacity: Decimal | None
    monthly_savings_amount: Decimal | None = None
    monthly_loan_payment: Decimal | None = None
    total_financial_cost: Decimal | None = None
    expected_net_savings_interest: Decimal | None = None
    cashflow_stability_score: Decimal | None = None
    plan_flexibility_score: Decimal | None = None
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name, value in (
            ("available_equity", self.available_equity),
            ("loan_capacity", self.loan_capacity),
            ("monthly_savings_amount", self.monthly_savings_amount),
            ("monthly_loan_payment", self.monthly_loan_payment),
            ("total_financial_cost", self.total_financial_cost),
            ("expected_net_savings_interest", self.expected_net_savings_interest),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")
        for name, value in (
            ("cashflow_stability_score", self.cashflow_stability_score),
            ("plan_flexibility_score", self.plan_flexibility_score),
        ):
            if value is not None and not Decimal(0) <= value <= Decimal(1):
                raise ValueError(f"{name}은(는) 0 이상 1 이하이어야 합니다.")


@dataclass(frozen=True)
class StrategyComparisonInput:
    as_of: date
    target_purchase_date: date
    housing_scenarios: tuple[HousingCostScenario, ...]
    asset_accumulation: StrategyCandidateInput
    early_purchase: StrategyCandidateInput
    policy: StrategyPolicy = DEFAULT_STRATEGY_POLICY

    def __post_init__(self) -> None:
        if self.target_purchase_date < self.as_of:
            raise ValueError("목표 구매일은 기준일보다 빠를 수 없습니다.")
        if not self.housing_scenarios:
            raise ValueError("주택가격 시나리오는 하나 이상이어야 합니다.")
        codes = [scenario.code for scenario in self.housing_scenarios]
        if len(codes) != len(set(codes)):
            raise ValueError("주택가격 시나리오 code는 중복될 수 없습니다.")
        if sum(scenario.is_baseline for scenario in self.housing_scenarios) != 1:
            raise ValueError("기준 주택가격 시나리오는 정확히 하나여야 합니다.")
        if self.asset_accumulation.kind is not StrategyKind.ASSET_ACCUMULATION:
            raise ValueError("asset_accumulation의 kind가 올바르지 않습니다.")
        if self.early_purchase.kind is not StrategyKind.EARLY_PURCHASE:
            raise ValueError("early_purchase의 kind가 올바르지 않습니다.")
        for candidate in (self.asset_accumulation, self.early_purchase):
            if (
                candidate.planned_purchase_date is not None
                and candidate.planned_purchase_date < self.as_of
            ):
                raise ValueError("예상 구매일은 기준일보다 빠를 수 없습니다.")


@dataclass(frozen=True)
class StrategyScoreComponents:
    scenario_attainment: Decimal | None
    cashflow_stability: Decimal | None
    total_financial_cost: Decimal | None
    goal_timing: Decimal | None
    plan_flexibility: Decimal | None


@dataclass(frozen=True)
class StrategyScenarioResult:
    scenario: HousingCostScenario
    strategy: StrategyKind
    target_purchase_cost: Decimal
    available_equity: Decimal | None
    loan_capacity: Decimal | None
    required_equity: Decimal | None
    equity_only_gap: Decimal | None
    expected_loan_amount: Decimal | None
    funding_capacity: Decimal | None
    funding_shortfall: Decimal | None
    coverage_ratio: Decimal | None
    status: StrategyScenarioStatus
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StrategyEvaluation:
    kind: StrategyKind
    planned_purchase_date: date | None
    target_purchase_date: date
    target_extension_required: bool | None
    target_delay_days: int | None
    available_equity: Decimal | None
    loan_capacity: Decimal | None
    monthly_savings_amount: Decimal | None
    monthly_loan_payment: Decimal | None
    total_financial_cost: Decimal | None
    expected_net_savings_interest: Decimal | None
    baseline_required_equity: Decimal | None
    baseline_expected_loan_amount: Decimal | None
    baseline_funding_shortfall: Decimal | None
    scenarios: tuple[StrategyScenarioResult, ...]
    attainable_count: int
    unattainable_count: int
    unknown_count: int
    scenario_coverage: Decimal | None
    score: Decimal | None
    score_status: StrategyScoreStatus
    score_completeness: Decimal
    score_components: StrategyScoreComponents
    missing_score_components: tuple[str, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StrategyComparisonResult:
    status: StrategyComparisonStatus
    as_of: date
    target_purchase_date: date
    asset_accumulation: StrategyEvaluation
    early_purchase: StrategyEvaluation
    leading_strategy: StrategyKind | None
    recommended_strategy: StrategyKind | None
    is_tie: bool
    missing_inputs: tuple[str, ...]
    reasons: tuple[str, ...]
    policy_note: str
    disclaimers: tuple[str, ...]
