"""계산 결과에서 생애주기 곡선에 필요한 점만 뽑는다.

이 모듈은 **새 값을 만들지 않는다.** 예·적금 배분과 대출 조합안이 이미 확정한
금액·기간·금리를 읽어 시간축 위의 점으로 바꿀 뿐이다.

무엇을 그리지 않는가:
    적립 구간의 **중간 시점 평가액**은 그리지 않는다. 배분 결과
    (``SavingsPortfolioAllocation``)에 이율·이자계산방식이 없어 중간 값을
    만들려면 지어내야 하기 때문이다. 대신 **납입 원금 누계**(확정)를 그리고,
    만기 평가액은 그 시점의 값 하나로만 밝힌다. 곡선을 예쁘게 만들려고 모르는
    구간을 보간하면, 그 선이 곧 "이때 깨면 이만큼 받는다"로 읽힌다.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from app.engines.lifecycle import LoanLeg, RepaymentKind, repayment_schedule
from app.reports.templates.lifecycle_chart import LifecycleChartInput, LifecyclePoint
from app.schemas.simulation import SectionRunStatus, SimulationResult

# 상환 곡선을 몇 달 간격으로 찍을지. 360개월을 전부 그리면 인쇄에서 선이 뭉개지고
# SVG만 수십 KB가 된다. 6개월 간격이면 30년 곡선의 모양이 그대로 남는다.
_REPAYMENT_STRIDE = 6

# 만기일시상환은 전세자금대출에서 나온다. 주택구입 목적 주담대는 원천 데이터상
# 모두 분할상환이므로 기본값은 원리금균등이다.
_BULLET_HINTS = ("만기일시", "일시상환")


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _section(simulation: SimulationResult, name: str) -> dict[str, object]:
    section = getattr(simulation, name, None)
    if section is None or section.run_status is not SectionRunStatus.COMPLETED:
        return {}
    return dict(section.result or {})


def _add_months(start: date, months: int) -> date:
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    last = 31
    if month != 12:
        last = (date(year + month // 12, month % 12 + 1, 1) - date.resolution).day
    return date(year, month, min(start.day, last))


def _repayment_kind(option_name: object) -> RepaymentKind:
    text = str(option_name or "")
    if any(hint in text for hint in _BULLET_HINTS):
        return RepaymentKind.BULLET
    return RepaymentKind.EQUAL_PAYMENT


def _accumulation_points(
    allocations: Sequence[object],
    *,
    as_of: date,
    purchase_date: date,
) -> tuple[tuple[LifecyclePoint, ...], Decimal | None]:
    """납입 원금 누계와 만기 평가액 합계.

    적금은 매달 같은 금액을 넣고 예금은 한 번 넣는다. 만기가 지난 상품은 더
    쌓이지 않는다 — 만기 뒤에도 계속 납입하는 것처럼 그리면 원금이 부풀어 오른다.
    """
    legs: list[tuple[str, Decimal, int]] = []
    maturity_total = Decimal(0)
    has_maturity = False
    for item in allocations:
        if not isinstance(item, Mapping):
            continue
        amount = _decimal(item.get("allocation_amount"))
        term = item.get("term_months")
        if amount is None or not isinstance(term, int) or term <= 0:
            continue
        basis = str(item.get("allocation_basis") or "")
        legs.append((basis, amount, term))
        value = _decimal(item.get("expected_maturity_amount"))
        if value is not None:
            maturity_total += value
            has_maturity = True

    if not legs:
        return (), None

    horizon = 0
    cursor = as_of
    while cursor < purchase_date and horizon < 600:
        horizon += 1
        cursor = _add_months(as_of, horizon)
    horizon = max(horizon, max(term for _basis, _amount, term in legs))

    points: list[LifecyclePoint] = [LifecyclePoint(at=as_of, amount=Decimal(0))]
    for index in range(1, horizon + 1):
        total = Decimal(0)
        for basis, amount, term in legs:
            elapsed = min(index, term)
            if basis.upper().startswith("LUMP"):
                total += amount
            else:
                total += amount * Decimal(elapsed)
        points.append(LifecyclePoint(at=_add_months(as_of, index), amount=total))
    return tuple(points), (maturity_total if has_maturity else None)


def _repayment_points(
    plan: Mapping[str, object],
    *,
    purchase_date: date,
) -> tuple[LifecyclePoint, ...]:
    """최선 조합안의 잔액 곡선. 다리마다 만기가 달라도 달 단위로 합친다."""
    legs_raw = plan.get("legs")
    if not isinstance(legs_raw, list):
        return ()

    schedules = []
    total_principal = Decimal(0)
    for item in legs_raw:
        if not isinstance(item, Mapping):
            continue
        amount = _decimal(item.get("amount"))
        rate = _decimal(item.get("annual_rate"))
        months = item.get("months")
        if amount is None or rate is None or not isinstance(months, int) or months <= 0:
            continue
        if amount <= 0:
            continue
        total_principal += amount
        schedules.append(
            repayment_schedule(
                LoanLeg(
                    product_name=str(item.get("product_name") or ""),
                    principal=amount,
                    annual_rate=rate,
                    months=months,
                    repayment_kind=_repayment_kind(item.get("option_name")),
                ),
                starts_on=purchase_date,
            )
        )
    if not schedules:
        return ()

    longest = max(len(rows) for rows in schedules)
    points: list[LifecyclePoint] = [
        LifecyclePoint(at=purchase_date, amount=total_principal)
    ]
    for index in range(longest):
        if (index + 1) % _REPAYMENT_STRIDE and index + 1 != longest:
            continue
        rows = [rows[index] for rows in schedules if index < len(rows)]
        points.append(
            LifecyclePoint(
                at=rows[0].as_of,
                amount=sum((row.balance for row in rows), Decimal(0)),
            )
        )
    return tuple(points)


def build_lifecycle_chart_input(
    simulation: SimulationResult,
) -> LifecycleChartInput | None:
    """가장 좋은 조합안 하나에 대한 생애주기. 그릴 수 없으면 ``None``.

    **최선안만 그린다.** 다섯 개를 모두 그리면 선이 겹쳐 어느 것이 어느 것인지
    읽히지 않고, 뒤 항목들이 이미 하나를 기준으로 서술하고 있다.
    """
    combination = _section(simulation, "loan_combination")
    plans = combination.get("plans")
    if not isinstance(plans, list) or not plans or not isinstance(plans[0], Mapping):
        return None

    purchase_date = simulation.goal.target_date
    if purchase_date <= simulation.as_of:
        # 목표 시점이 이미 지났으면 적립 구간이 성립하지 않는다.
        return None

    savings = _section(simulation, "savings_portfolio")
    allocations = savings.get("allocations")
    accumulation, maturity = _accumulation_points(
        allocations if isinstance(allocations, list) else (),
        as_of=simulation.as_of,
        purchase_date=purchase_date,
    )
    repayment = _repayment_points(plans[0], purchase_date=purchase_date)
    if not repayment:
        return None

    return LifecycleChartInput(
        accumulation=accumulation,
        repayment=repayment,
        purchase_date=purchase_date,
        maturity_value=maturity,
    )


__all__ = ["build_lifecycle_chart_input"]
