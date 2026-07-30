"""여러 대출을 **동시에** 실행하는 조합안의 입출력 계약.

목적:
    "주담대 3억 + 신용대출 1억" 같은 조합을 하나의 대안으로 다룬다. 기존
    `LoanComputation`은 상품 옵션 **하나**의 한도이고, 그것들을 더하면 안 된다 —
    DSR·현금흐름·LTV는 차주 한 명당 하나뿐인 **공유 예산**이라 다리끼리 잡아먹기
    때문이다. 개별 최대값의 합은 실제로 실행할 수 없는 금액이다.

기능:
    다리(상품 옵션) 후보, 공유 예산, 배분 결과와 §14 조합 점수를 정의한다.

근거:
    §9.1 LoanMax의 제약 목록과 부록 A-2의 단조성, §13.2/A-12 DSR 범위, 부록 A-8
    Buffer, §14 대출점수 다섯 항목을 그대로 쓴다. **조합 전용 가중치를 새로 만들지
    않는다** — §14 가중치를 조합 기준으로 다시 계산할 뿐이며, 그래서 가중치는
    `RecommendationPolicy` 하나에서만 나온다.

선형성이 이 계약의 근거다:
    PMT는 원금에 선형이다(`formulas.pmt`, PMT = L × c). 따라서 DSR·현금흐름·LTV
    제약이 모두 배분액의 선형 부등식이고, 남은 예산을 계수로 나누면 그 다리에
    넣을 수 있는 최대 원금이 바로 나온다. 예·적금 포트폴리오가
    `remaining / maturity_per_allocation`으로 공유 한도를 배분액으로 환산하는 것과
    같은 연산이다(`engines/savings/portfolio.py`의 `_institution_capacity`).

주의:
    이 모듈은 DB·Rule Pack·규제표를 모른다. 상품 한도·DTI 환산액·스트레스 심사
    금리는 앞 계층이 확정해 넣어야 한다. 확정하지 못한 값을 0이나 큰 수로 채우면
    안 된다 — 전자는 "빌릴 수 없음", 후자는 "제약 없음"으로 읽혀 둘 다 거짓이다.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.engines.loan.formulas import pmt
from app.engines.recommendation.models import (
    DEFAULT_RECOMMENDATION_POLICY,
    RecommendationPolicy,
    ScoreStatus,
)

# 신용대출 스트레스 가산금리가 붙기 시작하는 잔액. 규제 상수는
# `regulations/stress_dsr.py`가 소유하며, 순수 계산 계층은 그 모듈을 import하지
# 않는다(예적금 엔진이 예금자보호 한도를 입력으로 받는 것과 같은 규율). 그래서
# 문턱도 예산 객체의 입력으로 받는다.


class LoanLegKind(StrEnum):
    """다리가 어떤 공유 예산에 묶이는지 구분한다.

    - ``MORTGAGE``: 담보가 그 주택이므로 **LTV 예산을 함께 쓴다.**
    - ``CREDIT``: LTV와 무관하지만 잔액 문턱을 넘으면 심사금리가 올라간다.
    - ``OTHER``: 전세자금대출 등. LTV·문턱 어느 쪽에도 걸리지 않는다.

    세 종류 모두 DSR과 구매 후 현금흐름은 공유한다 — 그게 조합의 핵심 제약이다.
    """

    MORTGAGE = "MORTGAGE"
    CREDIT = "CREDIT"
    OTHER = "OTHER"


class CreditStressRegime(StrEnum):
    """신용대출 잔액이 스트레스 문턱의 어느 쪽인지.

    문턱이 있어 DSR 제약이 배분액에 대해 **꺾인다**(선형이 아니다). 그래서 구간을
    둘로 나눠 각 구간에서 선형으로 풀고, 전제가 성립하는 해만 채택한다.
    """

    NOT_APPLICABLE = "NOT_APPLICABLE"  # 신용대출 다리가 없음
    BELOW = "BELOW"  # 잔액이 문턱 이하 — 가산금리 미적용
    ABOVE = "ABOVE"  # 잔액이 문턱 초과 — 가산금리 적용


class CombinationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"  # 조합안은 있으나 필요 대출금액을 채우지 못함
    INFEASIBLE = "INFEASIBLE"  # 제약을 만족하는 조합이 없음
    UNRESOLVED = "UNRESOLVED"  # 입력을 확정하지 못해 계산하지 못함


@dataclass(frozen=True)
class LoanLegCandidate:
    """조합에 넣을 수 있는 다리 하나(상품 옵션 하나).

    ``maximum_amount=None``은 **확인된 무제한**이다(주택담보대출처럼 상품 고유
    상한이 없고 LTV·DTI 계산이 곧 한도인 경우). 미확인 한도는 이 계약에 넣지 말고
    앞 계층에서 결측으로 남겨야 한다 — 한도표(`LimitKind.UNCAPPED` vs
    ``UNKNOWN``)가 둘을 구분하는 이유와 같다.

    ``assessment_annual_rate``는 스트레스 DSR 심사금리이며 실제 금리보다 낮을 수
    없다. 실제 금리와 합치지 않는 이유는 쓰이는 곳이 다르기 때문이다 — DSR 판정은
    심사금리, 월 현금흐름은 실제 금리다. 뭉치면 한도가 약 28% 과대평가된다.
    """

    candidate_id: str
    product_id: str
    product_name: str
    option_name: str
    kind: LoanLegKind
    annual_rate: Decimal
    assessment_annual_rate: Decimal
    months: int
    maximum_amount: Decimal | None = None
    minimum_amount: Decimal | None = None
    # 옵션별 DTI 환산 한도. 금리·만기가 옵션마다 달라 DTI 금액도 옵션마다 다르다.
    # None은 DTI 규제 대상이 아니라는 뜻이며(비수도권), 미확인이면 앞 계층이
    # 후보에서 빼야 한다.
    dti_limit_amount: Decimal | None = None
    # 신용대출 잔액이 문턱을 **넘었을 때** 적용할 심사금리. ``CREDIT``인데 이 값이
    # None이면 문턱 위 구간을 계산하지 않는다 — 문턱 아래 금리로 계산해 버리면
    # 가산금리를 빠뜨려 한도가 과대평가된다.
    assessment_annual_rate_above_credit_threshold: Decimal | None = None
    additional_financial_cost: Decimal | None = None
    repayment_flexibility_score: Decimal | None = None
    rate_type_name: str | None = None
    # ``maximum_amount``가 무엇을 뜻하는지 만든 쪽이 이름을 붙인다. 조합안의
    # "묶은 제약"에 그대로 실리므로 정확해야 한다 — 상위 계층이 여러 상한의
    # 최솟값을 이 칸에 넣는 경우가 있고, 그때 "상품 한도"라고 표시하면 사용자에게
    # **틀린 사유**를 알려 준다.
    maximum_amount_label: str = "상품 한도"
    assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name, value in (
            ("candidate_id", self.candidate_id),
            ("product_id", self.product_id),
            ("product_name", self.product_name),
            ("option_name", self.option_name),
        ):
            if not value.strip():
                raise ValueError(f"{name}은(는) 비어 있을 수 없습니다.")
        if self.months <= 0:
            raise ValueError("months은(는) 0보다 커야 합니다.")
        if self.annual_rate < 0:
            raise ValueError("annual_rate은(는) 음수일 수 없습니다.")
        if self.assessment_annual_rate < self.annual_rate:
            raise ValueError("assessment_annual_rate는 실제 금리보다 낮을 수 없습니다.")
        above = self.assessment_annual_rate_above_credit_threshold
        if above is not None and above < self.assessment_annual_rate:
            raise ValueError(
                "문턱 위 심사금리는 문턱 아래 심사금리보다 낮을 수 없습니다."
            )
        if above is not None and self.kind is not LoanLegKind.CREDIT:
            raise ValueError("문턱 위 심사금리는 신용대출에만 의미가 있습니다.")
        for name, value in (
            ("maximum_amount", self.maximum_amount),
            ("minimum_amount", self.minimum_amount),
            ("dti_limit_amount", self.dti_limit_amount),
            ("additional_financial_cost", self.additional_financial_cost),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")
        if (
            self.maximum_amount is not None
            and self.minimum_amount is not None
            and self.maximum_amount < self.minimum_amount
        ):
            raise ValueError("maximum_amount은(는) minimum_amount보다 작을 수 없습니다.")
        if self.repayment_flexibility_score is not None and not (
            Decimal(0) <= self.repayment_flexibility_score <= Decimal(1)
        ):
            raise ValueError("repayment_flexibility_score은(는) 0 이상 1 이하여야 합니다.")

    @property
    def floor_amount(self) -> Decimal:
        return self.minimum_amount or Decimal(0)

    @property
    def payment_factor(self) -> Decimal:
        """원금 1원당 실제 월 상환액. 현금흐름 예산을 배분액으로 환산할 때 쓴다."""
        return pmt(Decimal(1), self.annual_rate, self.months)

    def assessment_payment_factor(self, *, above_threshold: bool) -> Decimal | None:
        """원금 1원당 심사 월 상환액. 확정할 수 없으면 None이다."""
        if not above_threshold or self.kind is not LoanLegKind.CREDIT:
            return pmt(Decimal(1), self.assessment_annual_rate, self.months)
        rate = self.assessment_annual_rate_above_credit_threshold
        if rate is None:
            return None
        return pmt(Decimal(1), rate, self.months)

    def assessment_rate_for(self, *, above_threshold: bool) -> Decimal | None:
        if not above_threshold or self.kind is not LoanLegKind.CREDIT:
            return self.assessment_annual_rate
        return self.assessment_annual_rate_above_credit_threshold


@dataclass(frozen=True)
class LoanCombinationBudget:
    """조합 전체가 공유하는 예산과 상한.

    이 객체의 존재 이유가 곧 이 엔진의 존재 이유다. 다리별 한도를 각각 계산해
    더하면 아래 예산을 다리 수만큼 중복 사용한다.
    """

    annual_income: Decimal
    existing_annual_debt_service: Decimal
    safe_dsr: Decimal
    post_purchase_monthly_income: Decimal
    post_purchase_monthly_expense: Decimal
    other_existing_monthly_debt_service: Decimal
    buffer_target: Decimal
    # 주담대 다리들이 **함께** 쓰는 상한. 담보가 같은 주택이므로 하나뿐이다.
    ltv_limit_amount: Decimal
    required_amount: Decimal
    # 신용대출 스트레스 문턱과 기존 잔액. 잔액을 모르면 신용대출이 든 조합을
    # 계산하지 않는다 — 0으로 뭉개면 문턱을 넘는 조합에 가산금리가 빠진다.
    credit_stress_threshold: Decimal | None = None
    existing_credit_loan_balance: Decimal | None = None

    def __post_init__(self) -> None:
        if self.annual_income <= 0:
            raise ValueError("annual_income은(는) 0보다 커야 합니다.")
        if self.safe_dsr <= 0 or self.safe_dsr > 1:
            raise ValueError("safe_dsr은(는) 0보다 크고 1 이하여야 합니다.")
        for name, value in (
            ("existing_annual_debt_service", self.existing_annual_debt_service),
            ("post_purchase_monthly_income", self.post_purchase_monthly_income),
            ("post_purchase_monthly_expense", self.post_purchase_monthly_expense),
            ("other_existing_monthly_debt_service", self.other_existing_monthly_debt_service),
            ("buffer_target", self.buffer_target),
            ("ltv_limit_amount", self.ltv_limit_amount),
            ("required_amount", self.required_amount),
        ):
            if value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")
        for name, value in (
            ("credit_stress_threshold", self.credit_stress_threshold),
            ("existing_credit_loan_balance", self.existing_credit_loan_balance),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")

    @property
    def annual_dsr_capacity(self) -> Decimal:
        """신규 대출이 쓸 수 있는 연 원리금 예산 = safe_dsr × 소득 − 기존 원리금."""
        return self.safe_dsr * self.annual_income - self.existing_annual_debt_service

    @property
    def monthly_cashflow_capacity(self) -> Decimal:
        """Buffer를 남기고 신규 대출 상환에 쓸 수 있는 월 금액(부록 A-8)."""
        return (
            self.post_purchase_monthly_income
            - self.post_purchase_monthly_expense
            - self.other_existing_monthly_debt_service
            - self.buffer_target
        )

    @property
    def credit_headroom_below_threshold(self) -> Decimal | None:
        """가산금리 없이 더 빌릴 수 있는 신용대출 금액. 확정 불가면 None."""
        if self.credit_stress_threshold is None:
            return None
        if self.existing_credit_loan_balance is None:
            return None
        return max(
            self.credit_stress_threshold - self.existing_credit_loan_balance,
            Decimal(0),
        )


@dataclass(frozen=True)
class LoanCombinationPolicy:
    """조합 탐색 범위와 점수 기준.

    §14 가중치는 여기서 정의하지 않고 `RecommendationPolicy`를 그대로 들고 있다 —
    단일 옵션 점수와 조합 점수가 다른 가중치를 쓰면 순위가 서로 모순된다.
    """

    # 예·적금 포트폴리오와 같은 이유로 3까지만 허용한다(조합 폭증 방지,
    # 역할분담 문서 §9.2). 오늘은 중복 이용 검수표가 실질적으로 2까지만 열어
    # 주지만, 그건 데이터 사실이므로 엔진 상한으로 굳히지 않는다.
    max_legs: int = 3
    # 사용자에게 보여줄 상위 조합 수. **자리를 채우려고 탈락한 조합을 끼워 넣지
    # 않는다** — 통과한 조합이 이보다 적으면 적은 대로 반환한다.
    top_n: int = 5
    # 배분 눈금. `loan_max`의 epsilon과 같은 단위이며, 이보다 작은 잔여 예산은
    # 다리에 배분하지 않는다.
    allocation_epsilon: Decimal = Decimal("100000")
    recommendation_policy: RecommendationPolicy = DEFAULT_RECOMMENDATION_POLICY

    def __post_init__(self) -> None:
        if self.max_legs < 1 or self.max_legs > 3:
            raise ValueError("max_legs은(는) 1 이상 3 이하여야 합니다.")
        if self.top_n < 1:
            raise ValueError("top_n은(는) 1 이상이어야 합니다.")
        if self.allocation_epsilon <= 0:
            raise ValueError("allocation_epsilon은(는) 0보다 커야 합니다.")


DEFAULT_COMBINATION_POLICY = LoanCombinationPolicy()


@dataclass(frozen=True)
class LoanLegAllocation:
    """조합안에서 다리 하나가 받은 금액과 그 결과."""

    candidate_id: str
    product_id: str
    product_name: str
    option_name: str
    kind: LoanLegKind
    amount: Decimal
    monthly_payment: Decimal
    assessment_monthly_payment: Decimal
    total_interest: Decimal
    annual_rate: Decimal
    assessment_annual_rate: Decimal
    months: int
    rate_type_name: str | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CombinationScoreComponents:
    """§14 다섯 항목을 조합 기준으로 계산한 값. None은 확인 불가다."""

    repayment_capacity: Decimal | None
    total_cost: Decimal | None
    crisis_resilience: Decimal | None
    interest_stability: Decimal | None
    repayment_flexibility: Decimal | None


@dataclass(frozen=True)
class LoanCombinationPlan:
    """조합안 하나 — 사용자에게 "방법 N"으로 보이는 단위."""

    plan_id: str
    legs: tuple[LoanLegAllocation, ...]
    total_amount: Decimal
    funding_shortfall: Decimal
    covers_required_amount: bool
    monthly_payment: Decimal
    assessment_monthly_payment: Decimal
    expected_dsr: Decimal
    assessment_dsr: Decimal
    post_purchase_monthly_surplus: Decimal
    stress_monthly_surplus: Decimal
    total_interest: Decimal
    total_financial_cost: Decimal | None
    credit_regime: CreditStressRegime
    # 이 금액을 묶은 제약. "왜 더 못 빌리는가"에 답하는 자리다.
    binding_constraints: tuple[str, ...] = field(default_factory=tuple)
    score: Decimal | None = None
    score_status: ScoreStatus = ScoreStatus.UNAVAILABLE
    score_completeness: Decimal = Decimal(0)
    score_components: CombinationScoreComponents | None = None
    missing_score_components: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def leg_count(self) -> int:
        return len(self.legs)

    @property
    def product_names(self) -> tuple[str, ...]:
        return tuple(leg.product_name for leg in self.legs)


@dataclass(frozen=True)
class ExcludedCombination:
    """탈락하거나 확정하지 못한 조합 하나와 그 사유.

    "안 됨"만 내보내지 않는다 — 확인된 불가는 사유를, 미확인은 무엇을 확인해야
    하는지를 담는다(§19).
    """

    product_names: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    sources: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LoanCombinationResult:
    """조합 탐색 결과."""

    status: CombinationStatus
    plans: tuple[LoanCombinationPlan, ...] = field(default_factory=tuple)
    considered_subsets: int = 0
    feasible_subsets: int = 0
    # 검수표가 불가로 판정한 조합.
    blocked: tuple[ExcludedCombination, ...] = field(default_factory=tuple)
    # 중복 이용 여부나 심사금리를 확정하지 못한 조합.
    unresolved: tuple[ExcludedCombination, ...] = field(default_factory=tuple)
    # 제약을 만족하지 못한 조합.
    infeasible: tuple[ExcludedCombination, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    policy_note: str = ""

    @property
    def best(self) -> LoanCombinationPlan | None:
        return self.plans[0] if self.plans else None


__all__ = [
    "DEFAULT_COMBINATION_POLICY",
    "CombinationScoreComponents",
    "CombinationStatus",
    "CreditStressRegime",
    "ExcludedCombination",
    "LoanCombinationBudget",
    "LoanCombinationPlan",
    "LoanCombinationPolicy",
    "LoanCombinationResult",
    "LoanLegAllocation",
    "LoanLegCandidate",
    "LoanLegKind",
]
