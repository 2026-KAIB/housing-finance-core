from datetime import date
from decimal import Decimal

import pytest

from app.engines.stress.engine import evaluate_stress_scenario, run_stress_test
from app.engines.stress.models import (
    DEFAULT_STRESS_SCENARIOS,
    InterestRateShockApplicability,
    StressCheck,
    StressScenario,
    StressScenarioKind,
    StressScenarioStatus,
    StressTestInput,
)

_AS_OF = date(2026, 7, 30)
_BASELINE = StressScenario(
    code="BASE",
    name="기준",
    kind=StressScenarioKind.BASELINE,
)
_RATE_UP = StressScenario(
    code="RATE",
    name="금리 1%p 상승",
    kind=StressScenarioKind.INTEREST_RATE,
    interest_rate_increase=Decimal("0.01"),
)
_INCOME_DOWN = StressScenario(
    code="INCOME",
    name="소득 20% 감소",
    kind=StressScenarioKind.INCOME,
    income_reduction_ratio=Decimal("0.20"),
)
_EXPENSE_UP = StressScenario(
    code="EXPENSE",
    name="생활비 20% 증가",
    kind=StressScenarioKind.LIVING_EXPENSE,
    living_expense_increase_ratio=Decimal("0.20"),
)


def _input(**overrides: object) -> StressTestInput:
    defaults: dict[str, object] = {
        "as_of": _AS_OF,
        "loan_principal": Decimal("100000000"),
        "annual_rate": Decimal("0.03"),
        "months": 360,
        "annual_income": Decimal("60000000"),
        "existing_annual_debt_service": Decimal("3000000"),
        "post_purchase_monthly_income": Decimal("5000000"),
        "post_purchase_monthly_expense": Decimal("1800000"),
        "other_existing_monthly_debt_service": Decimal("250000"),
        "monthly_essential_expense": Decimal("1800000"),
        "safe_dsr": Decimal("0.40"),
        "monthly_savings_commitment": Decimal("500000"),
        "interest_rate_shock_applicability": InterestRateShockApplicability.APPLIES,
        "scenarios": (_BASELINE,),
    }
    defaults.update(overrides)
    return StressTestInput(**defaults)  # type: ignore[arg-type]


def test_variable_rate_shock_recalculates_payment_dsr_and_cashflow() -> None:
    baseline = evaluate_stress_scenario(_input(), _BASELINE)
    stressed = evaluate_stress_scenario(_input(), _RATE_UP)

    assert stressed.applied_annual_rate == Decimal("0.04")
    assert stressed.monthly_payment > baseline.monthly_payment
    assert stressed.monthly_payment_increase > 0
    assert stressed.expected_dsr > baseline.expected_dsr
    assert stressed.buffer_margin < baseline.buffer_margin


def test_fixed_rate_does_not_fabricate_a_payment_increase() -> None:
    result = evaluate_stress_scenario(
        _input(
            interest_rate_shock_applicability=(
                InterestRateShockApplicability.NOT_APPLIES
            )
        ),
        _RATE_UP,
    )

    assert result.status is StressScenarioStatus.PASS
    assert result.applied_annual_rate == Decimal("0.03")
    assert result.monthly_payment_increase == 0
    assert any("고정금리" in reason for reason in result.reasons)


def test_unknown_rate_type_keeps_only_the_rate_scenario_unknown() -> None:
    payload = _input(
        interest_rate_shock_applicability=InterestRateShockApplicability.UNKNOWN
    )

    baseline = evaluate_stress_scenario(payload, _BASELINE)
    rate = evaluate_stress_scenario(payload, _RATE_UP)

    assert baseline.status is StressScenarioStatus.PASS
    assert rate.status is StressScenarioStatus.UNKNOWN
    assert rate.missing_inputs == ("interest_rate_shock_applicability",)
    assert rate.monthly_payment is None


def test_income_shock_changes_annual_and_monthly_income_consistently() -> None:
    result = evaluate_stress_scenario(_input(), _INCOME_DOWN)

    assert result.stressed_annual_income == Decimal("48000000")
    assert result.stressed_monthly_income == Decimal("4000000")
    assert result.expected_dsr is not None
    baseline = evaluate_stress_scenario(_input(), _BASELINE)
    assert result.expected_dsr > baseline.expected_dsr
    assert result.cashflow_before_savings < baseline.cashflow_before_savings


def test_living_expense_shock_also_recalculates_the_buffer_target() -> None:
    result = evaluate_stress_scenario(_input(), _EXPENSE_UP)

    assert result.stressed_monthly_expense == Decimal("2160000")
    assert result.stressed_monthly_essential_expense == Decimal("2160000")
    # 필수생활비의 10%는 216,000원이므로 공식 최소값 300,000원이 구속한다.
    assert result.buffer_target == Decimal("300000")
    baseline = evaluate_stress_scenario(_input(), _BASELINE)
    assert result.buffer_margin < baseline.buffer_margin


def test_savings_plan_failure_is_separate_from_loan_safety() -> None:
    result = evaluate_stress_scenario(
        _input(monthly_savings_commitment=Decimal("2500000")),
        _BASELINE,
    )

    assert result.dsr_within_limit is True
    assert result.buffer_maintained is True
    assert result.savings_plan_maintainable is False
    assert result.status is StressScenarioStatus.FAIL
    assert result.failed_checks == (StressCheck.SAVINGS_PLAN,)
    assert result.savings_shortfall > 0


def test_hard_cashflow_failure_has_priority_over_a_missing_savings_amount() -> None:
    result = evaluate_stress_scenario(
        _input(
            post_purchase_monthly_income=Decimal("1000000"),
            monthly_savings_commitment=None,
        ),
        _BASELINE,
    )

    assert result.status is StressScenarioStatus.FAIL
    assert StressCheck.CASH_BUFFER in result.failed_checks
    assert "monthly_savings_commitment" in result.missing_inputs


def test_default_suite_reports_nine_processed_scenarios() -> None:
    result = run_stress_test(
        _input(scenarios=DEFAULT_STRESS_SCENARIOS)
    )

    assert len(result.scenarios) == 9
    assert result.pass_count + result.fail_count + result.unknown_count == 9
    assert result.status is StressScenarioStatus.PASS
    assert result.pass_ratio == Decimal(1)
    assert result.maximum_dsr is not None
    assert result.minimum_buffer_margin is not None


def test_precondition_missing_input_makes_every_scenario_unknown() -> None:
    result = run_stress_test(
        _input(
            scenarios=(_BASELINE, _RATE_UP),
            precondition_missing_inputs=("recommended_loan_option",),
        )
    )

    assert result.status is StressScenarioStatus.UNKNOWN
    assert result.unknown_count == 2
    assert all(
        scenario.missing_inputs == ("recommended_loan_option",)
        for scenario in result.scenarios
    )


def test_scenario_kind_must_match_its_shock_values() -> None:
    with pytest.raises(ValueError, match="kind"):
        StressScenario(
            code="WRONG",
            name="잘못된 시나리오",
            kind=StressScenarioKind.INCOME,
            interest_rate_increase=Decimal("0.01"),
        )
