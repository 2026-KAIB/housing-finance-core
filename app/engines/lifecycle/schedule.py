"""적립 누계와 상환 스케줄을 월 단위로 펼친다.

이 모듈은 **기존 공식만 다시 부른다.** 적립 평가액은 예·적금 만기액 공식을
개월수만 바꿔 호출하고, 상환은 잔액 × 월금리로 이자를 떼는 표준 분해다.
새 이율도, 새 규제도 만들지 않는다.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.engines.lifecycle.models import (
    LoanLeg,
    RepaymentKind,
    RepaymentMonth,
    SavingsLeg,
    SavingsMonth,
)
from app.engines.loan.formulas import monthly_rate, pmt
from app.engines.savings.formulas import (
    installment_savings_gross_maturity,
    interest_tax,
    term_deposit_gross_maturity,
)
from app.engines.savings.models import (
    ContributionTiming,
    InterestType,
    SavingsProductKind,
)

# 이자소득세. 예·적금 계산이 쓰는 것과 같은 값을 쓴다 — 두 곳이 갈리면 같은
# 상품의 만기액이 화면과 생애주기에서 달라진다.
_INTEREST_TAX_RATE = Decimal("0.154")

_WON = Decimal(1)


def _won(value: Decimal) -> Decimal:
    """원 단위로 끊는다. 표시용 반올림과 계산용 값을 분리한다는 규약을 따른다."""
    return value.quantize(_WON, rounding=ROUND_HALF_UP)


def add_months(start: date, months: int) -> date:
    """말일 보정을 포함한 개월 더하기(1/31 + 1개월 = 2/28)."""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    if month == 12:
        last = 31
    else:
        last = (date(year + (month // 12), month % 12 + 1, 1) - date.resolution).day
    return date(year, month, min(start.day, last))


def _net_maturity(leg: SavingsLeg, months: int) -> Decimal:
    """``months``개월 유지했을 때의 세후 평가액.

    **만기까지 유지한다는 가정 아래의 값이다.** 중도해지이율은 상품마다 다르고
    원천 데이터에 없으므로 여기서 지어내지 않는다. 호출자가 이 값을 "지금 깨면
    받는 돈"으로 읽지 않도록 결과 모델이 납입 원금과 따로 담는다.
    """
    kind = SavingsProductKind(leg.kind)
    interest_type = InterestType(leg.interest_type)
    if kind is SavingsProductKind.TERM_DEPOSIT:
        gross = term_deposit_gross_maturity(
            principal=leg.lump_sum,
            annual_rate=leg.annual_rate,
            months=months,
            interest_type=interest_type,
        )
        principal = leg.lump_sum
    else:
        gross = installment_savings_gross_maturity(
            monthly_payment=leg.monthly_payment,
            annual_rate=leg.annual_rate,
            months=months,
            interest_type=interest_type,
            contribution_timing=ContributionTiming(leg.contribution_timing),
        )
        principal = leg.monthly_payment * Decimal(months)
    interest = gross - principal
    tax = interest_tax(gross_interest=interest, tax_rate=_INTEREST_TAX_RATE)
    return gross - tax


def savings_schedule(
    legs: tuple[SavingsLeg, ...],
    *,
    as_of: date,
    months: int,
) -> tuple[SavingsMonth, ...]:
    """오늘부터 ``months``개월까지 매달의 납입 누계와 유지 시 평가액.

    ``contributed``는 실제로 넣은 돈이라 **확정**이다. ``value_if_held``는 그 시점
    까지 유지했을 때의 세후 평가액이며, 만기가 지난 상품은 만기값에서 멈춘다 —
    만기 뒤에도 같은 이율이 붙는 것처럼 늘리지 않는다.
    """
    if months <= 0:
        return ()

    rows: list[SavingsMonth] = []
    for index in range(1, months + 1):
        contributed = Decimal(0)
        value = Decimal(0)
        for leg in legs:
            elapsed = min(index, leg.term_months)
            if SavingsProductKind(leg.kind) is SavingsProductKind.TERM_DEPOSIT:
                contributed += leg.lump_sum
            else:
                contributed += leg.monthly_payment * Decimal(elapsed)
            value += _net_maturity(leg, elapsed)
        rows.append(
            SavingsMonth(
                month_index=index,
                as_of=add_months(as_of, index),
                contributed=_won(contributed),
                value_if_held=_won(value),
            )
        )
    return tuple(rows)


def repayment_schedule(leg: LoanLeg, *, starts_on: date) -> tuple[RepaymentMonth, ...]:
    """대출 한 건의 월별 상환 내역.

    이자는 **그 달의 잔액**에 월금리를 곱해 뗀다. 원금은 상환액에서 이자를 뺀
    나머지다. 마지막 회차는 남은 잔액을 그대로 갚아 **잔액이 정확히 0으로 끝난다** —
    원 단위 반올림이 매달 쌓여 마지막에 몇 원이 남으면 "다 갚았는데 빚이 남은"
    문서가 된다.
    """
    if leg.principal <= 0:
        return ()

    i = monthly_rate(leg.annual_rate)
    balance = leg.principal
    rows: list[RepaymentMonth] = []

    if leg.repayment_kind is RepaymentKind.EQUAL_PAYMENT:
        payment = pmt(leg.principal, leg.annual_rate, leg.months)
    elif leg.repayment_kind is RepaymentKind.EQUAL_PRINCIPAL:
        payment = None  # 매달 달라진다
    else:
        payment = None  # 만기일시는 이자만

    flat_principal = leg.principal / Decimal(leg.months)

    for index in range(1, leg.months + 1):
        last = index == leg.months
        interest = _won(balance * i)

        if leg.repayment_kind is RepaymentKind.BULLET:
            principal_part = balance if last else Decimal(0)
        elif leg.repayment_kind is RepaymentKind.EQUAL_PRINCIPAL:
            principal_part = balance if last else _won(flat_principal)
        else:
            assert payment is not None
            principal_part = balance if last else _won(payment) - interest
            # 금리가 매우 낮으면 반올림 탓에 원금 상환분이 음수가 될 수 있다.
            # 잔액이 늘어나는 표를 만들지 않는다.
            principal_part = max(principal_part, Decimal(0))

        principal_part = min(principal_part, balance)
        balance = balance - principal_part
        rows.append(
            RepaymentMonth(
                month_index=index,
                as_of=add_months(starts_on, index),
                payment=_won(interest + principal_part),
                interest=interest,
                principal=_won(principal_part),
                balance=_won(balance),
            )
        )
    return tuple(rows)


__all__ = ["add_months", "repayment_schedule", "savings_schedule"]
