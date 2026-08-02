"""생애주기 — 적립·구매·상환을 하나의 시간축으로 잇는다.

여기서 고정하는 것은 두 가지다.

1. **표가 스스로 모순되지 않는다.** 잔액이 정확히 0으로 끝나고, 이자·원금 분해가
   상환액과 맞고, 만기 뒤에 이자가 더 붙지 않는다.
2. **모르는 것을 시간축 위에서 지어내지 않는다.** 구매 시점을 모르면 상환표를
   만들지 않는다 — 시작일을 모르는데 그리면 아직 사지도 않은 집의 상환이 이미
   시작된 문서가 나온다.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.engines.lifecycle import (
    LoanLeg,
    RepaymentKind,
    SavingsLeg,
    add_months,
    build_lifecycle,
    repayment_schedule,
    savings_schedule,
)

AS_OF = date(2026, 8, 1)
PURCHASE = date(2028, 8, 1)


def _mortgage(**changes: object) -> LoanLeg:
    values: dict[str, object] = {
        "product_name": "KB 주택담보대출",
        "principal": Decimal("300000000"),
        "annual_rate": Decimal("0.041"),
        "months": 360,
        "repayment_kind": RepaymentKind.EQUAL_PAYMENT,
    }
    values.update(changes)
    return LoanLeg(**values)  # type: ignore[arg-type]


_INSTALLMENT = SavingsLeg(
    product_name="KB적금",
    kind="installment_savings",
    monthly_payment=Decimal("1000000"),
    lump_sum=Decimal(0),
    annual_rate=Decimal("0.032"),
    term_months=24,
    interest_type="simple",
    contribution_timing="end",
)
_DEPOSIT = SavingsLeg(
    product_name="KB예금",
    kind="term_deposit",
    monthly_payment=Decimal(0),
    lump_sum=Decimal("50000000"),
    annual_rate=Decimal("0.030"),
    term_months=24,
    interest_type="simple",
    contribution_timing="end",
)


# --------------------------------------------------------------------------
# 상환표가 스스로 모순되지 않는다
# --------------------------------------------------------------------------


def test_the_balance_ends_at_exactly_zero() -> None:
    """원 단위 반올림이 매달 쌓이면 마지막에 몇 원이 남는다.

    "다 갚았는데 빚이 남은" 표는 문서로 나갈 수 없다.
    """
    rows = repayment_schedule(_mortgage(), starts_on=PURCHASE)

    assert len(rows) == 360
    assert rows[-1].balance == Decimal(0)


def test_every_row_splits_the_payment_into_interest_and_principal() -> None:
    """상환액 = 이자 + 원금. 한 줄이라도 어긋나면 표가 거짓말을 한다."""
    rows = repayment_schedule(_mortgage(), starts_on=PURCHASE)

    for row in rows:
        assert row.payment == row.interest + row.principal


def test_the_balance_decreases_by_exactly_the_principal_each_month() -> None:
    rows = repayment_schedule(_mortgage(), starts_on=PURCHASE)

    balance = Decimal("300000000")
    for row in rows:
        balance -= row.principal
        assert row.balance == balance


def test_interest_falls_and_principal_rises() -> None:
    """원리금균등의 정의다. 뒤집히면 잔액 계산이 틀린 것이다."""
    rows = repayment_schedule(_mortgage(), starts_on=PURCHASE)

    assert rows[0].interest > rows[-1].interest
    assert rows[0].principal < rows[-1].principal


def test_total_interest_matches_payments_minus_principal() -> None:
    """독립 검산 — 총 상환액 − 원금 = 총 이자."""
    rows = repayment_schedule(_mortgage(), starts_on=PURCHASE)

    paid = sum((row.payment for row in rows), Decimal(0))
    interest = sum((row.interest for row in rows), Decimal(0))
    assert paid - Decimal("300000000") == interest


# --------------------------------------------------------------------------
# 만기일시 — 전세대출의 구조
# --------------------------------------------------------------------------


def test_a_bullet_loan_pays_interest_only_until_maturity() -> None:
    """전세 만기에 보증금을 돌려받아 갚는 구조다. 원리금균등으로 계산하면 안 된다."""
    rows = repayment_schedule(
        _mortgage(
            principal=Decimal("200000000"),
            annual_rate=Decimal("0.035"),
            months=24,
            repayment_kind=RepaymentKind.BULLET,
        ),
        starts_on=AS_OF,
    )

    assert all(row.principal == Decimal(0) for row in rows[:-1])
    assert all(row.balance == Decimal("200000000") for row in rows[:-1])
    assert rows[-1].principal == Decimal("200000000")
    assert rows[-1].balance == Decimal(0)


def test_equal_principal_repays_the_same_principal_every_month() -> None:
    rows = repayment_schedule(
        _mortgage(months=12, repayment_kind=RepaymentKind.EQUAL_PRINCIPAL),
        starts_on=PURCHASE,
    )

    assert rows[0].principal == rows[5].principal
    assert rows[0].payment > rows[-1].payment  # 이자가 줄어드니 총액도 준다
    assert rows[-1].balance == Decimal(0)


def test_a_zero_principal_leg_has_no_schedule() -> None:
    """빌리지 않은 대출의 상환표를 만들지 않는다."""
    assert repayment_schedule(_mortgage(principal=Decimal(0)), starts_on=PURCHASE) == ()


# --------------------------------------------------------------------------
# 적립 — 확정된 원금과 가정된 평가액을 뭉개지 않는다
# --------------------------------------------------------------------------


def test_contributed_principal_is_separate_from_the_valuation() -> None:
    """중도해지 이율을 모르므로 "지금 깨면 받는 돈"을 하나의 숫자로 내지 않는다.

    합치면 그 값이 곧 중도 수령액으로 읽히고, 그건 수익을 크게 잡는 방향이다.
    """
    rows = savings_schedule((_INSTALLMENT,), as_of=AS_OF, months=24)

    assert rows[11].contributed == Decimal("12000000")
    assert rows[11].value_if_held is not None
    assert rows[11].value_if_held > rows[11].contributed


def test_contributions_accumulate_month_by_month() -> None:
    rows = savings_schedule((_INSTALLMENT,), as_of=AS_OF, months=24)

    assert rows[0].contributed == Decimal("1000000")
    assert rows[23].contributed == Decimal("24000000")


def test_a_lump_sum_deposit_is_counted_once_not_every_month() -> None:
    """예금은 한 번 넣는다. 매달 더하면 24개월 뒤 원금이 24배가 된다."""
    rows = savings_schedule((_DEPOSIT,), as_of=AS_OF, months=24)

    assert rows[0].contributed == Decimal("50000000")
    assert rows[23].contributed == Decimal("50000000")


def test_a_matured_product_stops_growing() -> None:
    """만기 뒤에도 같은 이율이 붙는 것처럼 늘리지 않는다."""
    rows = savings_schedule((_INSTALLMENT,), as_of=AS_OF, months=36)

    assert rows[23].value_if_held == rows[35].value_if_held
    assert rows[23].contributed == rows[35].contributed


def test_the_schedule_dates_advance_one_month_at_a_time() -> None:
    rows = savings_schedule((_INSTALLMENT,), as_of=AS_OF, months=3)

    assert [row.as_of for row in rows] == [
        date(2026, 9, 1),
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        (date(2026, 1, 31), 3, date(2026, 4, 30)),
        (date(2028, 1, 31), 1, date(2028, 2, 29)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),
    ],
)
def test_month_arithmetic_clamps_to_the_last_day(
    start: date,
    months: int,
    expected: date,
) -> None:
    """1월 31일 + 1개월은 2월 31일이 아니다."""
    assert add_months(start, months) == expected


# --------------------------------------------------------------------------
# 조립 — 모르는 것을 시간축 위에서 지어내지 않는다
# --------------------------------------------------------------------------


def test_the_three_phases_connect_end_to_end() -> None:
    result = build_lifecycle(
        as_of=AS_OF,
        savings_legs=(_INSTALLMENT, _DEPOSIT),
        loan_legs=(_mortgage(),),
        purchase_date=PURCHASE,
    )

    codes = [phase.code for phase in result.phases]
    assert codes == ["accumulation", "purchase", "repayment"]
    assert result.phases[0].ends_on == PURCHASE
    assert result.phases[2].starts_on == date(2028, 9, 1)
    assert result.repayment_ends_on == date(2058, 8, 1)


def test_no_purchase_date_means_no_repayment_schedule() -> None:
    """시작일을 모르는데 상환표를 그리면 아직 사지도 않은 집의 상환이 시작된다."""
    result = build_lifecycle(
        as_of=AS_OF,
        savings_legs=(_INSTALLMENT,),
        loan_legs=(_mortgage(),),
        purchase_date=None,
    )

    assert result.repayment_months == ()
    assert result.repayment_ends_on is None
    assert "purchase_date" in result.missing_inputs
    assert result.savings_months  # 적립 구간은 그대로 그린다


def test_no_savings_is_recorded_as_missing_not_as_a_plan_without_saving() -> None:
    """배분 0건과 '적립하지 않는 계획'은 다른 상태다."""
    result = build_lifecycle(as_of=AS_OF, loan_legs=(_mortgage(),), purchase_date=PURCHASE)

    assert result.savings_months == ()
    assert "savings_allocations" in result.missing_inputs
    assert result.total_contributed is None


def test_the_held_to_maturity_assumption_is_recorded() -> None:
    """숫자만 내보내면 근거 없는 확언이 된다(§20)."""
    result = build_lifecycle(as_of=AS_OF, savings_legs=(_INSTALLMENT,), purchase_date=PURCHASE)

    assert any("중도해지" in note for note in result.assumptions)
    assert any("계산 기준일에 시작" in note for note in result.assumptions)


def test_legs_with_different_maturities_are_merged_by_month() -> None:
    """조합 대출은 다리마다 만기가 다르다. 짧은 다리가 끝나도 표가 끊기면 안 된다."""
    result = build_lifecycle(
        as_of=AS_OF,
        savings_legs=(_INSTALLMENT,),
        loan_legs=(
            _mortgage(months=360),
            _mortgage(product_name="KB 신용대출", principal=Decimal("30000000"), months=60),
        ),
        purchase_date=PURCHASE,
    )

    assert len(result.repayment_months) == 360
    # 짧은 다리가 살아 있는 동안은 상환액이 더 크다.
    assert result.repayment_months[0].payment > result.repayment_months[120].payment
    assert result.repayment_months[-1].balance == Decimal(0)
