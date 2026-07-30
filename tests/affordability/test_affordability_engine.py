from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.engines.affordability import (
    AffordabilityVerdict,
    PropertyAffordabilityInput,
    evaluate_property_affordability,
)
from app.engines.loan.combination_models import (
    CombinationStatus,
    CreditStressRegime,
    LoanCombinationPlan,
    LoanCombinationResult,
)
from app.engines.purchase_costs import PurchaseCostInput, estimate_purchase_costs

_AS_OF = date(2026, 7, 30)
_PRICE = Decimal("100000000")


def _costs(*, registration: Decimal | None = Decimal("350000"), **overrides: object):
    values: dict[str, object] = {
        "as_of": _AS_OF,
        "purchase_price": _PRICE,
        "buyer_is_corporation": False,
        "household_home_count_after_purchase": 1,
        "is_registered_housing": True,
        "is_luxury_home": False,
        "exclusive_area_m2": Decimal("59"),
        "registration_and_legal_costs": registration,
    }
    values.update(overrides)
    return estimate_purchase_costs(PurchaseCostInput(**values))  # type: ignore[arg-type]


def _plan(
    target: Decimal,
    *,
    amount: Decimal | None = None,
    stress_surplus: Decimal = Decimal("1000000"),
) -> LoanCombinationPlan:
    loan_amount = target if amount is None else amount
    return LoanCombinationPlan(
        plan_id="plan-1",
        legs=(),
        total_amount=loan_amount,
        funding_shortfall=max(target - loan_amount, Decimal(0)),
        covers_required_amount=target - loan_amount <= Decimal("100000"),
        monthly_payment=Decimal("400000"),
        assessment_monthly_payment=Decimal("500000"),
        expected_dsr=Decimal("0.30"),
        assessment_dsr=Decimal("0.35"),
        post_purchase_monthly_surplus=Decimal("1200000"),
        stress_monthly_surplus=stress_surplus,
        total_interest=Decimal("20000000"),
        total_financial_cost=Decimal("20000000"),
        credit_regime=CreditStressRegime.NOT_APPLICABLE,
    )


def _combination(plan: LoanCombinationPlan) -> LoanCombinationResult:
    return LoanCombinationResult(
        status=(
            CombinationStatus.COMPLETE if plan.covers_required_amount else CombinationStatus.PARTIAL
        ),
        plans=(plan,),
    )


def _input(
    *,
    costs=None,
    usable: Decimal = Decimal("42000000"),
    protected: Decimal = Decimal("6000000"),
    target: Decimal = Decimal("6000000"),
    buffer: Decimal = Decimal("500000"),
    combination: LoanCombinationResult | None = None,
    loan_missing: tuple[str, ...] = (),
) -> PropertyAffordabilityInput:
    return PropertyAffordabilityInput(
        as_of=_AS_OF,
        listing_id="LISTING-1",
        purchase_price=_PRICE,
        purchase_costs=costs or _costs(),
        usable_liquid_assets=usable,
        emergency_fund_target=target,
        protected_liquid_assets=protected,
        cashflow_buffer_target=buffer,
        loan_combination=combination,
        loan_missing_inputs=loan_missing,
    )


def test_cash_purchase_is_affordable_without_a_loan_result() -> None:
    result = evaluate_property_affordability(_input(usable=Decimal("120000000")))

    assert result.verdict is AffordabilityVerdict.AFFORDABLE
    assert result.total_purchase_cost == Decimal("102000000")
    assert result.required_loan_amount == 0
    assert result.loan_funding_amount == 0
    assert result.own_funds_used == Decimal("102000000")
    assert result.remaining_usable_liquid_assets == Decimal("18000000")


def test_covering_combination_is_affordable_and_exposes_payment_metrics() -> None:
    required = Decimal("60000000")
    plan = _plan(required)

    result = evaluate_property_affordability(_input(combination=_combination(plan)))

    assert result.verdict is AffordabilityVerdict.AFFORDABLE
    assert result.required_loan_amount == required
    assert result.loan_funding_amount == required
    assert result.funding_gap == 0
    assert result.selected_loan_plan is plan
    assert result.monthly_loan_payment == Decimal("400000")


def test_tolerance_only_coverage_is_tight_not_fully_affordable() -> None:
    required = Decimal("60000000")
    plan = _plan(required, amount=required - Decimal("50000"))

    result = evaluate_property_affordability(_input(combination=_combination(plan)))

    assert result.verdict is AffordabilityVerdict.TIGHT
    assert result.funding_gap == Decimal("50000")
    assert any("허용오차" in reason for reason in result.reasons)


def test_stress_surplus_below_cashflow_buffer_is_tight() -> None:
    required = Decimal("60000000")
    plan = _plan(required, stress_surplus=Decimal("499999"))

    result = evaluate_property_affordability(_input(combination=_combination(plan)))

    assert result.verdict is AffordabilityVerdict.TIGHT
    assert any("스트레스" in reason for reason in result.reasons)


def test_underfunded_emergency_target_is_tight() -> None:
    result = evaluate_property_affordability(
        _input(
            usable=Decimal("120000000"),
            protected=Decimal("4000000"),
        )
    )

    assert result.verdict is AffordabilityVerdict.TIGHT
    assert any("비상자금 목표 대비" in reason for reason in result.reasons)


def test_confirmed_gap_above_tolerance_is_shortfall() -> None:
    required = Decimal("60000000")
    plan = _plan(required, amount=Decimal("50000000"))

    result = evaluate_property_affordability(_input(combination=_combination(plan)))

    assert result.verdict is AffordabilityVerdict.SHORTFALL
    assert result.funding_gap == Decimal("10000000")


def test_partial_cost_that_can_cover_only_the_minimum_remains_unknown() -> None:
    partial = _costs(registration=None)
    required_minimum = partial.minimum_total_purchase_cost - Decimal("42000000")
    plan = _plan(required_minimum)

    result = evaluate_property_affordability(_input(costs=partial, combination=_combination(plan)))

    assert result.verdict is AffordabilityVerdict.UNKNOWN
    assert result.total_purchase_cost is None
    assert result.required_loan_amount is None
    assert result.minimum_required_loan_amount == required_minimum
    assert result.funding_gap is None


def test_partial_cost_with_a_minimum_gap_can_be_rejected_definitively() -> None:
    partial = _costs(registration=None)
    required_minimum = partial.minimum_total_purchase_cost - Decimal("42000000")
    plan = _plan(required_minimum, amount=required_minimum - Decimal("1000000"))

    result = evaluate_property_affordability(_input(costs=partial, combination=_combination(plan)))

    assert result.verdict is AffordabilityVerdict.SHORTFALL
    assert result.minimum_funding_gap == Decimal("1000000")


def test_unresolved_loan_is_unknown_instead_of_zero() -> None:
    result = evaluate_property_affordability(_input(loan_missing=("loan_product_candidates",)))

    assert result.verdict is AffordabilityVerdict.UNKNOWN
    assert result.loan_funding_amount is None
    assert result.funding_gap is None
    assert "loan_product_candidates" in result.missing_inputs


def test_unsupported_purchase_cost_scope_stays_unsupported() -> None:
    unsupported = _costs(buyer_is_corporation=True)

    result = evaluate_property_affordability(_input(costs=unsupported))

    assert result.verdict is AffordabilityVerdict.UNSUPPORTED


def test_combination_for_another_required_amount_is_rejected() -> None:
    wrong = _plan(Decimal("59000000"))

    with pytest.raises(ValueError, match="different required amount"):
        evaluate_property_affordability(_input(combination=_combination(wrong)))


def test_input_rejects_a_purchase_cost_for_another_price() -> None:
    mismatched = _costs(purchase_price=Decimal("99000000"))

    with pytest.raises(ValueError, match="must match"):
        _input(costs=mismatched)


def test_result_contract_rejects_an_inconsistent_funding_gap() -> None:
    required = Decimal("60000000")
    result = evaluate_property_affordability(_input(combination=_combination(_plan(required))))

    with pytest.raises(ValueError, match="funding gap"):
        replace(result, funding_gap=Decimal("1"))
