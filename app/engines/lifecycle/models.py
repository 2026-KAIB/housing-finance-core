"""생애주기 계산의 입출력 계약.

이 엔진은 **새 사실을 만들지 않는다.** 이미 확정된 값(예·적금 배분, 대출 조합,
구매 시점)을 시간축에 펼쳐 놓을 뿐이다. 그래서 규제 판단도, 새 가정도 없다.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def _require_positive(value: int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name}은(는) 0보다 커야 합니다.")


class RepaymentKind(StrEnum):
    """상환방식. 원천 데이터의 ``rpay_type_nm``을 계산 관점으로 정규화한 값이다.

    주택구입 목적 주담대는 실제 상품이 모두 분할상환이다(원천 데이터 확인:
    "분할상환방식"·"원(리)금균등 분할상환"·"분할상환(원금균등/원리금균등/체증식)").
    만기일시는 전세자금대출에서 나오며, 그건 전세 만기에 보증금을 돌려받아
    갚는 구조라 별개다.
    """

    EQUAL_PAYMENT = "equal_payment"  # 원리금균등
    EQUAL_PRINCIPAL = "equal_principal"  # 원금균등
    BULLET = "bullet"  # 만기일시


@dataclass(frozen=True)
class SavingsLeg:
    """생애주기에 펼칠 예·적금 배분 한 건. 포트폴리오가 확정한 값만 받는다."""

    product_name: str
    kind: str  # SavingsProductKind 값
    monthly_payment: Decimal
    lump_sum: Decimal
    annual_rate: Decimal
    term_months: int
    interest_type: str  # InterestType 값
    contribution_timing: str  # ContributionTiming 값

    def __post_init__(self) -> None:
        _require_non_negative(self.monthly_payment, "monthly_payment")
        _require_non_negative(self.lump_sum, "lump_sum")
        _require_non_negative(self.annual_rate, "annual_rate")
        _require_positive(self.term_months, "term_months")


@dataclass(frozen=True)
class LoanLeg:
    """생애주기에 펼칠 대출 한 건. 조합 엔진이 확정한 금액·금리·만기를 받는다."""

    product_name: str
    principal: Decimal
    annual_rate: Decimal
    months: int
    repayment_kind: RepaymentKind

    def __post_init__(self) -> None:
        _require_non_negative(self.principal, "principal")
        _require_non_negative(self.annual_rate, "annual_rate")
        _require_positive(self.months, "months")


@dataclass(frozen=True)
class SavingsMonth:
    """적립 기간 중 한 달의 상태.

    ``contributed``는 **확정 사실**이고 ``value_if_held``는 **가정**이다.
    만기 전에 깨면 중도해지이율이 적용되는데 그 이율을 우리는 모른다. 그래서
    중간 시점 평가액을 하나의 숫자로 합치지 않고 둘로 나눠 둔다 — 합치면
    "지금 깨도 이만큼 받는다"로 읽히고, 그건 수익을 크게 잡는 방향이다.
    """

    month_index: int
    as_of: date
    contributed: Decimal
    value_if_held: Decimal | None


@dataclass(frozen=True)
class RepaymentMonth:
    """상환 기간 중 한 달."""

    month_index: int
    as_of: date
    payment: Decimal
    interest: Decimal
    principal: Decimal
    balance: Decimal


@dataclass(frozen=True)
class LifecyclePhase:
    """생애주기의 한 국면. 화면·문서가 이 목록만 읽으면 된다."""

    code: str
    name: str
    starts_on: date
    ends_on: date | None
    note: str = ""


@dataclass(frozen=True)
class LifecycleResult:
    as_of: date
    purchase_date: date | None
    repayment_ends_on: date | None
    savings_months: tuple[SavingsMonth, ...] = field(default_factory=tuple)
    repayment_months: tuple[RepaymentMonth, ...] = field(default_factory=tuple)
    phases: tuple[LifecyclePhase, ...] = field(default_factory=tuple)
    total_contributed: Decimal | None = None
    total_interest_paid: Decimal | None = None
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


__all__ = [
    "LifecyclePhase",
    "LifecycleResult",
    "LoanLeg",
    "RepaymentKind",
    "RepaymentMonth",
    "SavingsLeg",
    "SavingsMonth",
]
