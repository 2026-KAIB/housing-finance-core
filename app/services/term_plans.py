"""같은 대출을 갚는 두 가지 기간안을 나란히 만든다.

목적:
    만기를 "갚을 수 있는 가장 짧은 기간"으로 줄이면 총이자는 최소가 되지만
    충격 여유가 사라진다. 그 둘은 서로 다른 답이고, 어느 쪽이 나은지는 계산이
    정할 수 있는 문제가 아니라 **사용자가 고를 문제**다. 그래서 고르지 않고
    둘 다 싣는다.

기능:
    최소이자안(현재 계산 기간)과 충격대비안(스트레스를 통과하는 가장 짧은 기간)의
    기간·월 상환액·총이자·스트레스 판정을 함께 낸다.

근거:
    조달액은 기간에 따라 달라지지 않는다 — 기간이 바꾸는 것은 이자와 충격
    여유뿐이다. 그래서 두 안은 "얼마를 빌리나"가 아니라 "어떻게 갚나"의 선택지다.

    충격대비안을 찾을 때 **스트레스 판정식을 다시 만들지 않는다.** 같은 판정을
    두 벌 두면 둘이 갈리고, 갈린 쪽이 문서에 실린다. 실제 ``run_stress_test``를
    기간만 바꿔 가며 그대로 돌린다.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import StrEnum

from app.engines.loan.formulas import pmt, total_interest
from app.engines.stress.engine import run_stress_test
from app.engines.stress.models import (
    StressScenarioStatus,
    StressTestInput,
    StressTestResult,
)

TERM_PLANS_SCHEMA_VERSION = "term-plans@1.0.0"


class TermPlanKind(StrEnum):
    MINIMUM_INTEREST = "MINIMUM_INTEREST"
    STRESS_RESILIENT = "STRESS_RESILIENT"


_LABELS = {
    TermPlanKind.MINIMUM_INTEREST: "최소이자안",
    TermPlanKind.STRESS_RESILIENT: "충격대비안",
}


@dataclass(frozen=True)
class TermPlan:
    """기간 하나와, 그 기간을 골랐을 때 실제로 달라지는 값들."""

    kind: TermPlanKind
    label: str
    months: int
    monthly_payment: Decimal
    total_interest: Decimal
    stress_status: StressScenarioStatus
    # 문서의 나머지 절이 어느 안을 기준으로 서술되는지. 둘을 나란히 실어도 생애주기·
    # AI 설명은 하나를 기준으로 쓰이므로, 그게 어느 쪽인지 밝히지 않으면 읽는 쪽이
    # 두 숫자 중 어느 것이 문서의 기준인지 가릴 수 없다.
    is_basis: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TermPlanComparison:
    """두 기간안과, 둘을 비교할 수 있게 하는 공통 사실."""

    principal: Decimal
    annual_rate: Decimal
    plans: tuple[TermPlan, ...]
    # 충격대비안을 찾지 못한 이유. 못 찾은 것과 "찾을 필요가 없었다"는 다르다.
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)


def shortest_stress_resilient_months(
    payload: StressTestInput,
    *,
    maximum_months: int,
) -> int | None:
    """스트레스를 통과하는 가장 짧은 기간. 최대 기간으로도 못 통과하면 ``None``.

    판정은 실제 ``run_stress_test``다. 기간이 길어질수록 월 상환액이 작아지고
    DSR·Buffer가 함께 느슨해지므로 통과 여부는 기간에 대해 단조다 — 이분 탐색이
    성립한다.

    ``UNKNOWN``은 통과로 세지 않는다. 판정을 받지 못한 상태는 통과가 아니다.
    """
    if payload.months >= maximum_months:
        return payload.months if _passes(payload, payload.months) else None
    if not _passes(payload, maximum_months):
        return None
    if _passes(payload, payload.months):
        return payload.months

    low, high = payload.months, maximum_months
    while high - low > 1:
        middle = (low + high) // 2
        if _passes(payload, middle):
            high = middle
        else:
            low = middle
    return high


def _passes(payload: StressTestInput, months: int) -> bool:
    result = run_stress_test(replace(payload, months=months))
    return result.status is StressScenarioStatus.PASS


def _plan(
    kind: TermPlanKind,
    *,
    months: int,
    principal: Decimal,
    annual_rate: Decimal,
    stress_status: StressScenarioStatus,
    is_basis: bool = False,
    reasons: tuple[str, ...] = (),
) -> TermPlan:
    return TermPlan(
        kind=kind,
        label=_LABELS[kind],
        months=months,
        monthly_payment=pmt(principal, annual_rate, months),
        total_interest=total_interest(principal, annual_rate, months),
        stress_status=stress_status,
        is_basis=is_basis,
        reasons=reasons,
    )


def compare_term_plans(
    stress_payload: StressTestInput,
    stress_result: StressTestResult,
    *,
    maximum_months: int,
) -> TermPlanComparison | None:
    """기준안(=계산이 쓴 기간)과 충격대비안을 나란히 만든다.

    갚을 원금이 없으면 ``None``이다. 고를 것이 없는데 표를 실으면 0원짜리 두 안이
    나란히 놓인다.

    **원금은 두 안에서 같다고 본다.** 기간을 늘리면 DSR이 느슨해져 조달 한도는
    오히려 커지고, 실행액은 그 한도와 필요액 중 작은 값이므로 필요액에 걸려 있는
    한 달라지지 않는다. 한도에 걸려 있었다면 늘어날 수 있는데, 그 방향은 사용자에게
    유리하므로 여기서 고정하는 것이 과대평가가 아니다.
    """
    if stress_payload.loan_principal <= 0:
        return None

    basis = _plan(
        TermPlanKind.MINIMUM_INTEREST,
        months=stress_payload.months,
        principal=stress_payload.loan_principal,
        annual_rate=stress_payload.annual_rate,
        stress_status=stress_result.status,
        is_basis=True,
        reasons=("같은 금액을 갚을 수 있는 가장 짧은 기간입니다. 총이자가 가장 적습니다.",),
    )

    if stress_result.status is StressScenarioStatus.PASS:
        return TermPlanComparison(
            principal=stress_payload.loan_principal,
            annual_rate=stress_payload.annual_rate,
            plans=(basis,),
            reasons=("기준안이 이미 모든 스트레스 시나리오를 통과해 대안을 만들지 않았습니다.",),
        )

    resilient_months = shortest_stress_resilient_months(
        stress_payload,
        maximum_months=maximum_months,
    )
    if resilient_months is None:
        return TermPlanComparison(
            principal=stress_payload.loan_principal,
            annual_rate=stress_payload.annual_rate,
            plans=(basis,),
            missing_inputs=tuple(stress_result.scenarios[0].missing_inputs)
            if stress_result.status is StressScenarioStatus.UNKNOWN
            else (),
            reasons=(
                f"요청 만기 {maximum_months}개월까지 늘려도 스트레스를 통과하지 "
                "못해 충격대비안을 만들지 않았습니다. 기간이 아니라 금액이나 "
                "소득·지출 쪽을 봐야 합니다.",
            ),
        )

    resilient = _plan(
        TermPlanKind.STRESS_RESILIENT,
        months=resilient_months,
        principal=stress_payload.loan_principal,
        annual_rate=stress_payload.annual_rate,
        stress_status=StressScenarioStatus.PASS,
        reasons=("금리 상승·소득 감소·생활비 증가 시나리오를 모두 통과하는 가장 짧은 기간입니다.",),
    )
    extra = resilient.total_interest - basis.total_interest
    lighter = basis.monthly_payment - resilient.monthly_payment
    return TermPlanComparison(
        principal=stress_payload.loan_principal,
        annual_rate=stress_payload.annual_rate,
        plans=(basis, resilient),
        reasons=(
            f"충격대비안은 기준안보다 {resilient.months - basis.months}개월 길고 "
            f"총이자가 {extra.quantize(Decimal(1)):,}원 많습니다. "
            f"월 상환액은 {lighter.quantize(Decimal(1)):,}원 작아집니다.",
            "조달액은 두 안이 같습니다. 기간은 이자와 충격 여유만 바꿉니다.",
        ),
        assumptions=(
            "두 안의 대출 실행액이 같다고 보고 비교했습니다. 기간을 늘리면 DSR이 "
            "느슨해져 조달 한도는 오히려 커지므로, 필요액에 걸려 있는 한 실행액은 "
            "달라지지 않습니다.",
        ),
    )


__all__ = [
    "TERM_PLANS_SCHEMA_VERSION",
    "TermPlan",
    "TermPlanComparison",
    "TermPlanKind",
    "compare_term_plans",
    "shortest_stress_resilient_months",
]
