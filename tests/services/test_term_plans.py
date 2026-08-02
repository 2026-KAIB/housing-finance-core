"""같은 대출을 갚는 두 기간안을 나란히 낸다.

여기서 고정하는 것은 네 가지다.

1. **고르지 않는다.** 이자를 적게 낼 것인가 충격 여유를 둘 것인가는 계산이 정할
   문제가 아니다. 두 안을 다 내고 값을 정확히 적는 데까지가 계산의 몫이다.
2. **판정식을 두 벌 두지 않는다.** 충격대비안은 실제 ``run_stress_test``를 기간만
   바꿔 돌려 찾는다. 예측식을 새로 만들면 문서의 두 절이 갈린다.
3. **UNKNOWN은 통과가 아니다.** 판정을 받지 못한 상태를 통과로 세면 대안이 실제로
   견디는지 모르는 채 권하게 된다.
4. **못 찾은 것과 만들 필요가 없었던 것은 다르다.**
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.engines.stress.engine import run_stress_test
from app.engines.stress.models import (
    DEFAULT_STRESS_SCENARIOS,
    InterestRateShockApplicability,
    StressScenarioStatus,
    StressTestInput,
)
from app.services.term_plans import (
    TermPlanKind,
    compare_term_plans,
    shortest_stress_resilient_months,
)

_AS_OF = date(2026, 8, 3)
_PRINCIPAL = Decimal("119941406")
_RATE = Decimal("0.041")


def _input(months: int, **overrides) -> StressTestInput:
    """월소득 1,000만원 차주. 34개월은 못 견디고 기간을 늘리면 견딘다."""
    base = {
        "as_of": _AS_OF,
        "loan_principal": _PRINCIPAL,
        "annual_rate": _RATE,
        "months": months,
        "annual_income": Decimal("120000000"),
        "existing_annual_debt_service": Decimal(0),
        "post_purchase_monthly_income": Decimal("10000000"),
        "post_purchase_monthly_expense": Decimal("3000000"),
        "other_existing_monthly_debt_service": Decimal(0),
        "monthly_essential_expense": Decimal("3000000"),
        "safe_dsr": Decimal("0.40"),
        "monthly_savings_commitment": Decimal(0),
        "interest_rate_shock_applicability": InterestRateShockApplicability.APPLIES,
        "scenarios": DEFAULT_STRESS_SCENARIOS,
    }
    base.update(overrides)
    return StressTestInput(**base)


def test_the_resilient_term_is_the_shortest_one_that_actually_passes() -> None:
    """찾은 기간은 통과하고, 그보다 한 달 짧으면 통과하지 못해야 한다.

    "통과하는 기간"만 확인하면 필요 이상으로 긴 기간도 통과한다. 경계를 함께
    봐야 **가장 짧은** 기간임이 고정된다.
    """
    payload = _input(34)
    months = shortest_stress_resilient_months(payload, maximum_months=360)

    assert months is not None
    assert months > payload.months
    assert run_stress_test(replace(payload, months=months)).status is StressScenarioStatus.PASS
    assert (
        run_stress_test(replace(payload, months=months - 1)).status
        is not StressScenarioStatus.PASS
    )


def test_a_term_that_already_passes_is_returned_unchanged() -> None:
    """이미 견디는 기간을 늘리면 이자만 더 내게 된다."""
    payload = _input(360)

    assert shortest_stress_resilient_months(payload, maximum_months=360) == 360


def test_an_unknown_verdict_is_never_counted_as_passing() -> None:
    """판정을 받지 못한 상태는 통과가 아니다.

    적금 납입 계획을 모르면 모든 시나리오가 UNKNOWN이 된다. 그걸 통과로 세면
    "견딥니다"라고 쓴 대안이 실제로는 판정된 적이 없는 계획이 된다.
    """
    payload = _input(34, monthly_savings_commitment=None)

    # 기간을 최대로 늘려도 판정이 확정되지 않는다 — FAIL은 사라지지만 UNKNOWN이
    # 남는다. 그 상태를 통과로 세면 안 된다.
    assert run_stress_test(replace(payload, months=360)).status is StressScenarioStatus.UNKNOWN
    assert shortest_stress_resilient_months(payload, maximum_months=360) is None


def test_a_plan_that_never_passes_yields_no_alternative() -> None:
    """최대 기간으로도 못 견디면 기간이 아니라 금액이 문제다."""
    payload = _input(34, post_purchase_monthly_expense=Decimal("9500000"))

    assert shortest_stress_resilient_months(payload, maximum_months=360) is None


class TestTheComparison:
    def test_it_offers_both_plans_and_names_the_basis(self) -> None:
        """둘을 나란히 싣되 문서가 어느 쪽으로 쓰였는지 밝힌다."""
        payload = _input(34)
        comparison = compare_term_plans(
            payload, run_stress_test(payload), maximum_months=360
        )

        assert comparison is not None
        kinds = [plan.kind for plan in comparison.plans]
        assert kinds == [TermPlanKind.MINIMUM_INTEREST, TermPlanKind.STRESS_RESILIENT]

        basis = [plan for plan in comparison.plans if plan.is_basis]
        assert len(basis) == 1
        assert basis[0].kind is TermPlanKind.MINIMUM_INTEREST

    def test_the_longer_plan_costs_more_interest_and_less_each_month(self) -> None:
        """이 부등호가 두 안의 존재 이유다. 뒤집히면 고를 것이 없다."""
        payload = _input(34)
        comparison = compare_term_plans(
            payload, run_stress_test(payload), maximum_months=360
        )

        assert comparison is not None
        cheapest, resilient = comparison.plans
        assert resilient.months > cheapest.months
        assert resilient.total_interest > cheapest.total_interest
        assert resilient.monthly_payment < cheapest.monthly_payment

    def test_the_two_plans_borrow_the_same_amount(self) -> None:
        """기간이 조달액을 바꾼다고 읽히면 사용자가 금액을 포기했다고 오해한다."""
        payload = _input(34)
        comparison = compare_term_plans(
            payload, run_stress_test(payload), maximum_months=360
        )

        assert comparison is not None
        assert comparison.principal == _PRINCIPAL
        assert any("조달액은 두 안이 같습니다" in text for text in comparison.reasons)

    def test_a_passing_basis_gets_no_alternative_and_says_why(self) -> None:
        """"대안을 못 만들었다"와 "만들 필요가 없었다"는 다른 상태다."""
        payload = _input(360)
        comparison = compare_term_plans(
            payload, run_stress_test(payload), maximum_months=360
        )

        assert comparison is not None
        assert len(comparison.plans) == 1
        assert any("이미" in text and "통과" in text for text in comparison.reasons)

    def test_no_loan_means_no_table(self) -> None:
        """갚을 것이 없는데 표를 실으면 0원짜리 두 안이 나란히 놓인다."""
        payload = _input(360, loan_principal=Decimal(0), annual_rate=Decimal(0))

        assert compare_term_plans(payload, run_stress_test(payload), maximum_months=360) is None
