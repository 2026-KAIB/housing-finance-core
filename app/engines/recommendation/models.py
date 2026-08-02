"""대출과 예·적금 결과를 종합추천 계층에 전달하는 불변 계약.

목적:
    종합추천 엔진이 DB 행, FastAPI 스키마, 서비스 객체를 직접 알지 않게 한다.
    상위 조립 계층은 이미 계산·검증된 결과를 이 계약으로 변환하고, 엔진은
    같은 입력에 항상 같은 추천 순위와 상태를 반환한다.
기능:
    대출 후보와 차주 재무상태, 정책검증이 끝난 예·적금 배분안, 추천 가중치,
    최종 추천 결과를 ``Decimal`` 기반 dataclass로 정의한다.
근거:
    공식 설계안 §14의 대출 MCDA 가중치와 §19의 추천·탈락 사유 및 기준일 표시,
    ``app/engines/savings/README.md``의 "최종 정책검증 PASS만 종합추천으로 전달"
    규약을 따른다. 공식 문서가 정하지 않은 임곗값은 ``RecommendationPolicy``에
    노출해 숨은 상수로 만들지 않는다.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class DecisionStatus(StrEnum):
    """상위 정책 판정 결과. UNKNOWN은 FAIL이나 0점이 아니다."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class SavingsPlanStatus(StrEnum):
    """예·적금 포트폴리오 엔진 결과를 종합추천 계약으로 옮긴 상태."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INFEASIBLE = "INFEASIBLE"
    NO_ALLOCATION_REQUIRED = "NO_ALLOCATION_REQUIRED"


class ComponentStatus(StrEnum):
    """대출·예적금 각 구성요소가 추천에 사용 가능한 정도."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    INFEASIBLE = "INFEASIBLE"
    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_REQUESTED = "NOT_REQUESTED"


class ScoreStatus(StrEnum):
    """MCDA 점수에 필요한 구성요소가 얼마나 확인됐는지."""

    COMPLETE = "COMPLETE"
    PROVISIONAL = "PROVISIONAL"
    UNAVAILABLE = "UNAVAILABLE"


class RecommendationStatus(StrEnum):
    """종합추천 결과의 완성도이며 대출 승인 여부를 뜻하지 않는다."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INFEASIBLE = "INFEASIBLE"


@dataclass(frozen=True)
class RecommendationPolicy:
    """공식 설계안의 대출점수 가중치와 서비스 내부 비교 기준.

    앞의 다섯 가중치는 공식 설계안 §14의 기본값이다. 나머지 값은 공식 규제가
    아니라 MVP 내부 기준이므로 결과에 ``policy_note``로 표시하고 호출자가 교체할
    수 있게 한다.
    """

    repayment_capacity_weight: Decimal = Decimal("0.30")
    total_cost_weight: Decimal = Decimal("0.25")
    crisis_resilience_weight: Decimal = Decimal("0.20")
    interest_stability_weight: Decimal = Decimal("0.15")
    repayment_flexibility_weight: Decimal = Decimal("0.10")
    maximum_payment_increase_ratio: Decimal = Decimal("0.20")
    minimum_score_completeness: Decimal = Decimal("0.60")
    loan_amount_tolerance: Decimal = Decimal("100000")
    max_loan_recommendations: int = 3
    policy_note: str = (
        "대출점수 가중치는 공식 설계안 §14, 결측 허용률·상환액 증가 허용폭은 "
        "서비스 내부 추천 기준입니다."
    )

    def __post_init__(self) -> None:
        weights = self.weights
        for name, value in weights.items():
            if value < 0 or value > 1:
                raise ValueError(f"{name}은(는) 0 이상 1 이하이어야 합니다.")
        if sum(weights.values(), Decimal(0)) != Decimal(1):
            raise ValueError("대출점수 가중치 합은 1이어야 합니다.")
        if self.maximum_payment_increase_ratio < 0:
            raise ValueError("maximum_payment_increase_ratio은(는) 음수일 수 없습니다.")
        if not Decimal(0) <= self.minimum_score_completeness <= Decimal(1):
            raise ValueError("minimum_score_completeness은(는) 0 이상 1 이하이어야 합니다.")
        if self.loan_amount_tolerance < 0:
            raise ValueError("loan_amount_tolerance은(는) 음수일 수 없습니다.")
        if self.max_loan_recommendations < 1:
            raise ValueError("max_loan_recommendations은(는) 1 이상이어야 합니다.")
        if not self.policy_note.strip():
            raise ValueError("policy_note은(는) 비어 있을 수 없습니다.")

    @property
    def weights(self) -> dict[str, Decimal]:
        return {
            "repayment_capacity": self.repayment_capacity_weight,
            "total_cost": self.total_cost_weight,
            "crisis_resilience": self.crisis_resilience_weight,
            "interest_stability": self.interest_stability_weight,
            "repayment_flexibility": self.repayment_flexibility_weight,
        }


DEFAULT_RECOMMENDATION_POLICY = RecommendationPolicy()


@dataclass(frozen=True)
class LoanCandidateInput:
    """대출 시뮬레이션을 통과한 실행 가능 옵션 하나.

    ``maximum_amount``는 이미 상품한도·LTV·DTI·DSR·현금흐름 제한을 모두 적용한
    보수적 가능액이다. 종합추천 엔진은 이 값을 늘리지 않는다.

    ``additional_financial_cost``가 None이면 보증료·인지비용·수수료를 모르는
    상태다. 0으로 대체하지 않아 총비용 점수를 임시값으로 꾸미지 않는다.
    """

    candidate_id: str
    product_name: str
    option_name: str
    maximum_amount: Decimal
    annual_rate: Decimal
    assessment_annual_rate: Decimal | None
    # 스트레스 생활 시나리오가 고정·변동금리를 문자열 추측 없이 구분하도록
    # 정규화된 옵션의 금리유형을 별도 보존한다.
    rate_type_name: str | None = None
    additional_financial_cost: Decimal | None = None
    repayment_flexibility_score: Decimal | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("product_name", self.product_name),
            ("option_name", self.option_name),
        ):
            if not value.strip():
                raise ValueError(f"{name}은(는) 비어 있을 수 없습니다.")
        if self.maximum_amount < 0:
            raise ValueError("maximum_amount은(는) 음수일 수 없습니다.")
        if self.annual_rate < 0:
            raise ValueError("annual_rate은(는) 음수일 수 없습니다.")
        if (
            self.assessment_annual_rate is not None
            and self.assessment_annual_rate < self.annual_rate
        ):
            raise ValueError("assessment_annual_rate는 실제 금리보다 낮을 수 없습니다.")
        if self.additional_financial_cost is not None and self.additional_financial_cost < 0:
            raise ValueError("additional_financial_cost은(는) 음수일 수 없습니다.")
        if self.repayment_flexibility_score is not None and not (
            Decimal(0) <= self.repayment_flexibility_score <= Decimal(1)
        ):
            raise ValueError("repayment_flexibility_score은(는) 0 이상 1 이하이어야 합니다.")


@dataclass(frozen=True)
class LoanRecommendationInput:
    """동일 금액·동일 기간으로 대출 후보를 비교하기 위한 완전한 공통 입력."""

    required_amount: Decimal
    months: int
    annual_income: Decimal
    existing_annual_debt_service: Decimal
    post_purchase_monthly_income: Decimal
    post_purchase_monthly_expense: Decimal
    other_existing_monthly_debt_service: Decimal
    buffer_target: Decimal
    safe_dsr: Decimal
    candidates: tuple[LoanCandidateInput, ...] = field(default_factory=tuple)
    unresolved_count: int = 0
    rejected_count: int = 0
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    policy_sources: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.required_amount < 0:
            raise ValueError("required_amount은(는) 음수일 수 없습니다.")
        if self.months <= 0:
            raise ValueError("months은(는) 0보다 커야 합니다.")
        if self.annual_income <= 0:
            raise ValueError("annual_income은(는) 0보다 커야 합니다.")
        for name, value in (
            ("existing_annual_debt_service", self.existing_annual_debt_service),
            ("post_purchase_monthly_income", self.post_purchase_monthly_income),
            ("post_purchase_monthly_expense", self.post_purchase_monthly_expense),
            (
                "other_existing_monthly_debt_service",
                self.other_existing_monthly_debt_service,
            ),
            ("buffer_target", self.buffer_target),
            ("safe_dsr", self.safe_dsr),
        ):
            if value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")
        if self.required_amount > 0 and self.safe_dsr <= 0:
            raise ValueError("대출이 필요하면 safe_dsr은(는) 0보다 커야 합니다.")
        if self.unresolved_count < 0 or self.rejected_count < 0:
            raise ValueError("후보 상태 개수는 음수일 수 없습니다.")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("대출 candidate_id은(는) 중복될 수 없습니다.")


@dataclass(frozen=True)
class SavingsAllocationInput:
    """정책 재검증을 통과한 예·적금 최종 배분 한 건."""

    candidate_id: str
    product_name: str
    product_kind: str
    institution_name: str
    allocation_amount: Decimal
    term_months: int
    maturity_date: date
    expected_maturity_amount: Decimal
    expected_net_interest: Decimal
    product_score: Decimal
    source_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("product_name", self.product_name),
            ("product_kind", self.product_kind),
            ("institution_name", self.institution_name),
            ("source_version", self.source_version),
        ):
            if not value.strip():
                raise ValueError(f"{name}은(는) 비어 있을 수 없습니다.")
        if self.allocation_amount <= 0:
            raise ValueError("allocation_amount은(는) 0보다 커야 합니다.")
        if self.term_months <= 0:
            raise ValueError("term_months은(는) 0보다 커야 합니다.")
        for name, value in (
            ("expected_maturity_amount", self.expected_maturity_amount),
            ("expected_net_interest", self.expected_net_interest),
            ("product_score", self.product_score),
        ):
            if value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


@dataclass(frozen=True)
class SavingsPlanInput:
    """예·적금 엔진 결과와 최종 상품정책 재검증 상태."""

    status: SavingsPlanStatus
    policy_status: DecisionStatus
    allocations: tuple[SavingsAllocationInput, ...]
    coverage_ratio: Decimal
    monthly_allocated: Decimal
    monthly_unallocated: Decimal
    lump_sum_allocated: Decimal
    lump_sum_unallocated: Decimal
    expected_total_principal: Decimal
    expected_maturity_amount: Decimal
    expected_net_interest: Decimal
    reasons: tuple[str, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not Decimal(0) <= self.coverage_ratio <= Decimal(1):
            raise ValueError("coverage_ratio은(는) 0 이상 1 이하이어야 합니다.")
        for name, value in (
            ("monthly_allocated", self.monthly_allocated),
            ("monthly_unallocated", self.monthly_unallocated),
            ("lump_sum_allocated", self.lump_sum_allocated),
            ("lump_sum_unallocated", self.lump_sum_unallocated),
            ("expected_total_principal", self.expected_total_principal),
            ("expected_maturity_amount", self.expected_maturity_amount),
            ("expected_net_interest", self.expected_net_interest),
        ):
            if value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


@dataclass(frozen=True)
class CombinedRecommendationInput:
    """종합추천 순수 함수가 소비하는 최상위 입력."""

    as_of: date
    loan: LoanRecommendationInput | None = None
    savings: SavingsPlanInput | None = None
    policy: RecommendationPolicy = DEFAULT_RECOMMENDATION_POLICY

    def __post_init__(self) -> None:
        if self.loan is None and self.savings is None:
            raise ValueError("대출 또는 예·적금 결과 중 하나는 필요합니다.")


@dataclass(frozen=True)
class LoanScoreComponents:
    repayment_capacity: Decimal | None
    total_cost: Decimal | None
    crisis_resilience: Decimal | None
    interest_stability: Decimal | None
    repayment_flexibility: Decimal | None


@dataclass(frozen=True)
class LoanOptionRecommendation:
    candidate_id: str
    product_name: str
    option_name: str
    maximum_amount: Decimal
    recommended_amount: Decimal
    funding_shortfall: Decimal
    covers_required_amount: bool
    annual_rate: Decimal
    assessment_annual_rate: Decimal | None
    rate_type_name: str | None
    monthly_payment: Decimal
    stress_monthly_payment: Decimal | None
    total_interest: Decimal
    total_financial_cost: Decimal | None
    expected_dsr: Decimal
    post_purchase_monthly_surplus: Decimal
    stress_monthly_surplus: Decimal | None
    score: Decimal | None
    score_status: ScoreStatus
    score_completeness: Decimal
    score_components: LoanScoreComponents
    missing_score_components: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LoanRecommendationSummary:
    status: ComponentStatus
    required_amount: Decimal
    maximum_recommendable_amount: Decimal
    funding_shortfall: Decimal
    primary: LoanOptionRecommendation | None
    alternatives: tuple[LoanOptionRecommendation, ...]
    unresolved_count: int
    rejected_count: int
    # 추천된 대출을 **실제로 갚는 기간**. 요청 만기가 아니다 — 계산 계층이 갚을 수
    # 있는 가장 짧은 기간으로 줄이면 둘은 달라진다(`shorten_to_serviceable_term`).
    #
    # 이 값이 없으면 뒤에 오는 계층이 요청 만기로 되돌아가고, 그러면 월 상환액을
    # 실제보다 **작게** 잡는다. 스트레스 판정이 그만큼 느슨해지므로 위험한 방향이다.
    # 추천할 대출이 없을 때만 ``None``이며, 그때는 갚을 원금도 없다.
    months: int | None = None
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    policy_sources: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SavingsRecommendationSummary:
    status: ComponentStatus
    plan_status: SavingsPlanStatus | None
    policy_status: DecisionStatus | None
    allocations: tuple[SavingsAllocationInput, ...]
    coverage_ratio: Decimal
    monthly_unallocated: Decimal
    lump_sum_unallocated: Decimal
    expected_maturity_amount: Decimal
    expected_net_interest: Decimal
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CombinedRecommendationResult:
    """AI 설명과 API가 그대로 사용할 수 있는 결정론적 종합추천 결과."""

    status: RecommendationStatus
    as_of: date
    loan: LoanRecommendationSummary
    savings: SavingsRecommendationSummary
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    policy_note: str
    disclaimers: tuple[str, ...]
