"""적립 → 구매 → 상환을 하나의 시간축으로 잇는다.

목적:
    "언제부터 얼마를 모아서, 언제 얼마를 빌려, 언제 집을 사고, 언제 다 갚는가"에
    한 번에 답한다. 지금까지는 구간별 숫자는 있었지만 그 숫자들이 **시간축 위에서
    어떻게 이어지는지**를 아무도 말해 주지 않았다.

무엇을 하지 않는가:
    새 사실을 만들지 않는다. 적립액·대출액·구매 시점은 앞 엔진들이 확정한 값을
    받아 펼치기만 한다. 구매 시점을 모르면 **추측하지 않고** 적립 구간까지만
    그리고 나머지를 결측으로 남긴다 — 구매일을 지어내면 상환 완료일까지 통째로
    지어낸 문서가 된다.
"""

from datetime import date
from decimal import Decimal

from app.engines.lifecycle.models import (
    LifecyclePhase,
    LifecycleResult,
    LoanLeg,
    RepaymentMonth,
    SavingsLeg,
)
from app.engines.lifecycle.schedule import (
    add_months,
    repayment_schedule,
    savings_schedule,
)

_HELD_TO_MATURITY = (
    "적립 평가액은 만기까지 유지했을 때의 세후 금액입니다. 중도해지 이율은 "
    "상품마다 달라 반영하지 않았으므로, 중간에 해지하면 실제 수령액은 더 적습니다."
)
_SAVINGS_START_TODAY = "모든 적립을 계산 기준일에 시작한다고 보았습니다."


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _merge_repayments(
    schedules: tuple[tuple[RepaymentMonth, ...], ...],
) -> tuple[RepaymentMonth, ...]:
    """여러 대출의 상환표를 달 단위로 합친다.

    조합 대출은 다리마다 만기가 다를 수 있다. 짧은 다리가 끝난 뒤에는 그 다리의
    상환액이 0이 되고 잔액도 0이므로, 합계는 **그 달에 살아 있는 다리만** 더한다.
    """
    if not schedules:
        return ()
    longest = max(len(rows) for rows in schedules)
    merged: list[RepaymentMonth] = []
    for index in range(longest):
        rows = [s[index] for s in schedules if index < len(s)]
        merged.append(
            RepaymentMonth(
                month_index=index + 1,
                as_of=rows[0].as_of,
                payment=sum((r.payment for r in rows), Decimal(0)),
                interest=sum((r.interest for r in rows), Decimal(0)),
                principal=sum((r.principal for r in rows), Decimal(0)),
                balance=sum((r.balance for r in rows), Decimal(0)),
            )
        )
    return tuple(merged)


def build_lifecycle(
    *,
    as_of: date,
    savings_legs: tuple[SavingsLeg, ...] = (),
    loan_legs: tuple[LoanLeg, ...] = (),
    purchase_date: date | None = None,
) -> LifecycleResult:
    """적립·구매·상환을 하나의 생애주기로 묶는다.

    ``purchase_date``가 없으면 상환 구간을 만들지 않는다. 대출을 언제 받는지
    모르는데 상환표를 그리면 시작일이 곧 오늘이 되어, 아직 사지도 않은 집의
    상환이 이미 시작된 문서가 나온다.
    """
    missing: list[str] = []
    assumptions: list[str] = []
    reasons: list[str] = []

    savings_months = ()
    total_contributed: Decimal | None = None
    if savings_legs:
        assumptions.append(_SAVINGS_START_TODAY)
        assumptions.append(_HELD_TO_MATURITY)
        horizon = (
            _months_between(as_of, purchase_date)
            if purchase_date is not None
            else max(leg.term_months for leg in savings_legs)
        )
        horizon = max(horizon, 0)
        if horizon == 0:
            reasons.append(
                "구매 시점이 계산 기준일과 같은 달이라 적립 구간을 만들지 않았습니다."
            )
        savings_months = savings_schedule(savings_legs, as_of=as_of, months=horizon)
        if savings_months:
            total_contributed = savings_months[-1].contributed
    else:
        missing.append("savings_allocations")
        reasons.append(
            "예·적금 배분이 없어 적립 구간을 만들지 않았습니다. "
            "배분 0건과 '적립하지 않는 계획'은 다른 상태입니다."
        )

    repayment_months: tuple[RepaymentMonth, ...] = ()
    repayment_ends_on: date | None = None
    total_interest: Decimal | None = None
    if not loan_legs:
        missing.append("loan_plan")
        reasons.append("확정된 대출 조합이 없어 상환 구간을 만들지 않았습니다.")
    elif purchase_date is None:
        missing.append("purchase_date")
        reasons.append(
            "구매 시점을 확정하지 못해 상환 구간을 만들지 않았습니다. "
            "시작일을 모르면 상환 완료일도 확정할 수 없습니다."
        )
    else:
        merged = _merge_repayments(
            tuple(repayment_schedule(leg, starts_on=purchase_date) for leg in loan_legs)
        )
        repayment_months = merged
        if merged:
            repayment_ends_on = merged[-1].as_of
            total_interest = sum((row.interest for row in merged), Decimal(0))

    phases: list[LifecyclePhase] = []
    if savings_months:
        phases.append(
            LifecyclePhase(
                code="accumulation",
                name="적립",
                starts_on=as_of,
                ends_on=savings_months[-1].as_of,
                note=f"{len(savings_months)}개월 적립",
            )
        )
    if purchase_date is not None:
        phases.append(
            LifecyclePhase(
                code="purchase",
                name="구매",
                starts_on=purchase_date,
                ends_on=purchase_date,
            )
        )
    if repayment_months and repayment_ends_on is not None:
        phases.append(
            LifecyclePhase(
                code="repayment",
                name="상환",
                starts_on=add_months(purchase_date, 1) if purchase_date else as_of,
                ends_on=repayment_ends_on,
                note=f"{len(repayment_months)}개월 상환",
            )
        )

    return LifecycleResult(
        as_of=as_of,
        purchase_date=purchase_date,
        repayment_ends_on=repayment_ends_on,
        savings_months=savings_months,
        repayment_months=repayment_months,
        phases=tuple(phases),
        total_contributed=total_contributed,
        total_interest_paid=total_interest,
        missing_inputs=tuple(dict.fromkeys(missing)),
        assumptions=tuple(dict.fromkeys(assumptions)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = ["build_lifecycle"]
