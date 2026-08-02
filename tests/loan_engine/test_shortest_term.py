"""갚을 수 있는 가장 짧은 기간.

만기를 요청값 그대로 쓰면 **갚을 수 있는데도 필요 이상으로 오래 갚는다.**
원리금균등에서 총이자는 기간에 대해 단조증가하므로, 같은 금액이면 짧을수록 싸다.

여기서 고정하는 것은 두 가지다.

1. **경계가 정확하다.** 돌려준 기간은 되고 그보다 한 달 짧으면 안 된다.
2. **판정이 ``loan_max``와 같다.** 더 느슨한 기준으로 짧은 기간을 권하면
   실행할 수 없는 계획이 된다 — 한도는 되는데 기간은 안 되는 조합이 나온다.
"""

from decimal import Decimal

import pytest

from app.engines.loan.formulas import (
    buffer,
    loan_max,
    pmt,
    shortest_serviceable_months,
    term_is_serviceable,
    total_interest,
)

_PRINCIPAL = Decimal("300000000")
_RATE = Decimal("0.041")
_DSR_RATE = Decimal("0.071")  # 실제 + 스트레스 3.0%p


def _borrower(monthly_income: str = "10000000", **changes: object) -> dict[str, object]:
    income = Decimal(monthly_income)
    values: dict[str, object] = {
        "annual_income": income * 12,
        "existing_annual_debt_service": Decimal(0),
        "safe_dsr": Decimal("0.40"),
        "post_purchase_monthly_income": income,
        "post_purchase_monthly_expense": Decimal("3000000"),
        "other_existing_monthly_debt_service": Decimal(0),
        "buffer_target": buffer(Decimal("2500000")),
    }
    values.update(changes)
    return values


def _shortest(**changes: object) -> int | None:
    kwargs: dict[str, object] = {
        "principal": _PRINCIPAL,
        "annual_rate": _RATE,
        "dsr_annual_rate": _DSR_RATE,
        "maximum_months": 360,
        **_borrower(),
    }
    kwargs.update(changes)
    return shortest_serviceable_months(**kwargs)  # type: ignore[arg-type]


def _serviceable(months: int, **changes: object) -> bool:
    kwargs: dict[str, object] = {
        "principal": _PRINCIPAL,
        "annual_rate": _RATE,
        "dsr_annual_rate": _DSR_RATE,
        "months": months,
        **_borrower(),
    }
    kwargs.update(changes)
    return term_is_serviceable(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 경계가 정확하다
# --------------------------------------------------------------------------


def test_the_answer_is_serviceable_and_one_month_shorter_is_not() -> None:
    """"가장 짧은"의 정의 그대로다. 한 달이라도 더 줄일 수 있으면 답이 아니다."""
    months = _shortest()

    assert months is not None
    assert _serviceable(months)
    assert not _serviceable(months - 1)


def test_a_high_earner_does_not_need_thirty_years() -> None:
    """월소득 1,000만원이 3억을 빌리는데 360개월을 쓸 이유가 없다."""
    months = _shortest()

    assert months is not None
    assert months < 360


def test_a_shorter_term_costs_less_interest() -> None:
    """이 계산의 존재 이유다. 짧을수록 총이자가 적어야 한다."""
    months = _shortest()

    assert months is not None
    saved = total_interest(_PRINCIPAL, _RATE, 360) - total_interest(_PRINCIPAL, _RATE, months)
    assert saved > 0


def test_the_monthly_payment_rises_as_the_term_shortens() -> None:
    """짧게 갚으면 매달 더 낸다. 그래서 "현실적인가"를 따져야 한다."""
    months = _shortest()

    assert months is not None
    assert pmt(_PRINCIPAL, _RATE, months) > pmt(_PRINCIPAL, _RATE, 360)


# --------------------------------------------------------------------------
# 단조성 — 이분 탐색이 성립하는 근거
# --------------------------------------------------------------------------


def test_serviceability_never_flips_back_as_the_term_grows() -> None:
    """기간이 늘면 상환액이 줄어 DSR도 현금흐름도 함께 완화된다.

    이 성질이 깨지면 이분 탐색이 엉뚱한 답을 준다.
    """
    seen_true = False
    for months in range(1, 361):
        ok = _serviceable(months)
        if ok:
            seen_true = True
        else:
            assert not seen_true, f"{months}개월에서 되돌아갔다"


def test_the_search_agrees_with_a_linear_scan() -> None:
    """이분 탐색 결과가 처음부터 하나씩 훑은 답과 같은지 확인한다."""
    scanned = next(
        (months for months in range(1, 361) if _serviceable(months)),
        None,
    )

    assert _shortest() == scanned


# --------------------------------------------------------------------------
# 판정이 loan_max와 같다
# --------------------------------------------------------------------------


def test_the_recommended_term_can_actually_borrow_the_amount() -> None:
    """한도 계산과 기간 계산이 같은 식을 쓴다는 것을 실제 값으로 확인한다.

    두 곳이 갈리면 "한도로는 되는데 기간으로는 안 되는" 조합이 나온다.
    """
    months = _shortest()
    assert months is not None

    borrowed = loan_max(
        ltv_limit_amount=_PRINCIPAL,
        product_limit_amount=_PRINCIPAL,
        dti_limit_amount=_PRINCIPAL,
        required_amount=_PRINCIPAL,
        annual_rate=_RATE,
        months=months,
        dsr_annual_rate=_DSR_RATE,
        **_borrower(),  # type: ignore[arg-type]
    )

    # 탐색 오차(epsilon 100,000) 안에서 필요액 전액을 조달한다.
    assert _PRINCIPAL - borrowed <= Decimal("100000")


def test_one_month_shorter_cannot_borrow_the_full_amount() -> None:
    """반대 방향도 확인한다 — 더 짧게 하면 한도가 모자란다."""
    months = _shortest()
    assert months is not None

    borrowed = loan_max(
        ltv_limit_amount=_PRINCIPAL,
        product_limit_amount=_PRINCIPAL,
        dti_limit_amount=_PRINCIPAL,
        required_amount=_PRINCIPAL,
        annual_rate=_RATE,
        months=months - 1,
        dsr_annual_rate=_DSR_RATE,
        **_borrower(),  # type: ignore[arg-type]
    )

    assert borrowed < _PRINCIPAL


# --------------------------------------------------------------------------
# 두 금리를 분리한다
# --------------------------------------------------------------------------


def test_the_stress_rate_makes_the_term_longer_not_shorter() -> None:
    """DSR은 심사금리로 본다. 실제 금리로 판정하면 기간이 짧게 나와 한도가 부푼다."""
    with_stress = _shortest()
    without_stress = _shortest(dsr_annual_rate=None)

    assert with_stress is not None and without_stress is not None
    assert with_stress > without_stress


def test_an_assessment_rate_below_the_actual_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="낮을 수 없습니다"):
        _serviceable(360, dsr_annual_rate=Decimal("0.01"))


# --------------------------------------------------------------------------
# 갚을 수 없으면 기간을 늘려 답을 만들지 않는다
# --------------------------------------------------------------------------


def test_an_unaffordable_amount_returns_nothing() -> None:
    """최대 기간으로도 못 갚으면 **기간이 아니라 금액이 문제**다.

    임의로 기간을 늘려 "가능"을 만들면 실행할 수 없는 계획이 나간다.
    """
    assert _shortest(**_borrower("2500000")) is None


def test_a_tight_buffer_can_bind_before_dsr() -> None:
    """현금흐름 Buffer가 DSR보다 먼저 물릴 수 있다. 두 조건을 모두 본다."""
    generous_dsr = _shortest(**_borrower("10000000", safe_dsr=Decimal("0.99")))
    tight_cashflow = _shortest(
        **_borrower(
            "10000000",
            safe_dsr=Decimal("0.99"),
            post_purchase_monthly_expense=Decimal("7000000"),
        )
    )

    assert generous_dsr is not None and tight_cashflow is not None
    assert tight_cashflow > generous_dsr


def test_existing_debt_pushes_the_term_out() -> None:
    """기존 부채가 DSR 예산을 먼저 먹으면 같은 금액을 더 오래 갚아야 한다."""
    loose = _shortest()
    burdened = _shortest(
        **_borrower("10000000", existing_annual_debt_service=Decimal("12000000"))
    )

    assert loose is not None and burdened is not None
    assert burdened > loose


# --------------------------------------------------------------------------
# 인수 검증
# --------------------------------------------------------------------------


def test_the_minimum_bound_is_honoured() -> None:
    """상품이 최소 만기를 정한 경우 그보다 짧게 권하지 않는다."""
    floor = _shortest(minimum_months=240)

    assert floor == 240


def test_a_maximum_below_the_minimum_is_refused() -> None:
    with pytest.raises(ValueError, match="작을 수 없습니다"):
        _shortest(minimum_months=120, maximum_months=60)


def test_total_interest_grows_with_the_term() -> None:
    """총이자가 기간에 대해 단조증가한다 — 짧은 쪽을 찾는 이유 그 자체다."""
    values = [total_interest(_PRINCIPAL, _RATE, m) for m in (60, 120, 240, 360)]

    assert values == sorted(values)
