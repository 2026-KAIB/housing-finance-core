from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class SavingsProductKind(StrEnum):
    """계산 관점의 예적금 상품 구분."""

    TERM_DEPOSIT = "term_deposit"
    INSTALLMENT_SAVINGS = "installment_savings"


class InterestType(StrEnum):
    """상품이 공시한 이자 계산 방식."""

    SIMPLE = "simple"
    COMPOUND = "compound"


class ContributionTiming(StrEnum):
    """적립식 납입 시점."""

    BEGINNING = "beginning"
    END = "end"


class SavingsEvaluationStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


@dataclass(frozen=True)
class SavingsCalculationInput:
    """예적금 순수 계산기가 소비하는 완전한 입력.

    금액 단위는 원, 금리는 비율(3% → ``Decimal("0.03")``), 기간은 개월이다.
    예금은 ``deposit_amount``만, 적금은 ``monthly_payment_amount``와
    ``contribution_timing``만 사용한다.
    """

    product_name: str
    product_kind: SavingsProductKind
    term_months: int
    interest_type: InterestType
    annual_base_rate: Decimal
    annual_max_rate: Decimal
    bonus_achievement_probability: Decimal
    tax_rate: Decimal
    reserve_type_name: str | None = None
    deposit_amount: Decimal | None = None
    monthly_payment_amount: Decimal | None = None
    contribution_timing: ContributionTiming | None = None


@dataclass(frozen=True)
class SavingsCalculationResult:
    """옵션 하나의 만기 보유 가정 계산 결과."""

    product_name: str
    product_kind: SavingsProductKind
    term_months: int
    interest_type: InterestType
    reserve_type_name: str | None
    annual_base_rate: Decimal
    annual_max_rate: Decimal
    expected_annual_rate: Decimal
    bonus_achievement_probability: Decimal
    total_principal: Decimal
    gross_interest: Decimal
    tax_amount: Decimal
    net_interest: Decimal
    maturity_amount: Decimal
    annualized_net_return_rate: Decimal
    net_return_rate: Decimal


@dataclass(frozen=True)
class SavingsScoreComponents:
    rate_score: Decimal
    maturity_fit_score: Decimal
    liquidity_score: Decimal
    safety_score: Decimal
    bonus_achievement_score: Decimal


@dataclass(frozen=True)
class SavingsEvaluationInput:
    """계산 결과를 주택구매 목적에 맞게 평가하기 위한 입력.

    ``liquidity_score``는 중도해지이율이 아직 구조화되지 않았으므로 상위 정책
    계층이 0~1 값으로 제공한다. 금리 점수의 정규화 범위도 후보군을 아는 상위
    계층이 명시해, 단일 상품 계산기가 다른 후보를 조회하지 않게 한다.
    """

    calculation: SavingsCalculationResult
    as_of: date
    fund_needed_date: date
    maturity_tolerance_days: int
    market_min_rate: Decimal
    market_max_rate: Decimal
    liquidity_score: Decimal
    is_principal_protected: bool
    accepts_principal_risk: bool
    is_deposit_protected: bool
    existing_institution_deposit: Decimal
    deposit_protection_limit: Decimal


@dataclass(frozen=True)
class SavingsEvaluationResult:
    product_name: str
    term_months: int
    maturity_date: date
    projected_institution_deposit: Decimal
    status: SavingsEvaluationStatus
    score: Decimal | None = None
    components: SavingsScoreComponents | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)
