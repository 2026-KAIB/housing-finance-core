from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.rule_engine.savings import (
    SavingsEligibilityContext,
    SavingsProduct,
    evaluate_savings_eligibility,
)

AS_OF = date(2026, 7, 23)

BASE_PRODUCT = SavingsProduct(
    product_id="savings-01",
    name="청년우대적금(placeholder)",
    operating_institution="샘플은행",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=date(2026, 12, 31),
    confirmed_date=date(2026, 7, 1),
    source_url="https://example.bank/savings",
    min_monthly_payment=Decimal("100000"),
    max_monthly_payment=Decimal("500000"),
    maturity_months=24,
    is_principal_protected=True,
    is_deposit_protected=True,
)

BASE_CONTEXT = SavingsEligibilityContext(
    as_of=AS_OF,
    product=BASE_PRODUCT,
    is_membership_eligible=True,
    planned_monthly_payment=Decimal("300000"),
    fund_needed_date=date(2028, 12, 31),
    product_maturity_date=date(2028, 7, 1),
    accepts_principal_risk=False,
    projected_deposit_at_institution=Decimal("40000000"),
    deposit_protection_limit=Decimal("50000000"),
    preferential_conditions_feasible=True,
)


def test_fully_eligible_savings_product_passes_every_rule() -> None:
    result = evaluate_savings_eligibility(BASE_CONTEXT)

    assert result.eligible is True
    assert result.reasons == ()


def test_not_a_member_fails() -> None:
    context = replace(BASE_CONTEXT, is_membership_eligible=False)

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_MEMBERSHIP_ELIGIBILITY" for d in result.failed_decisions)


def test_payment_below_minimum_fails() -> None:
    context = replace(BASE_CONTEXT, planned_monthly_payment=Decimal("50000"))

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_PAYMENT_RANGE" for d in result.failed_decisions)


def test_payment_above_maximum_fails() -> None:
    context = replace(BASE_CONTEXT, planned_monthly_payment=Decimal("600000"))

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_PAYMENT_RANGE" for d in result.failed_decisions)


def test_payment_at_boundaries_passes() -> None:
    at_min = evaluate_savings_eligibility(
        replace(BASE_CONTEXT, planned_monthly_payment=BASE_PRODUCT.min_monthly_payment)
    )
    at_max = evaluate_savings_eligibility(
        replace(BASE_CONTEXT, planned_monthly_payment=BASE_PRODUCT.max_monthly_payment)
    )

    assert at_min.eligible is True
    assert at_max.eligible is True


def test_maturity_after_fund_needed_date_fails() -> None:
    context = replace(BASE_CONTEXT, product_maturity_date=date(2029, 1, 1))

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_MATURITY_ALIGNMENT" for d in result.failed_decisions)


def test_maturity_exactly_on_fund_needed_date_passes() -> None:
    context = replace(BASE_CONTEXT, product_maturity_date=BASE_CONTEXT.fund_needed_date)

    result = evaluate_savings_eligibility(context)

    assert result.eligible is True


def test_principal_at_risk_product_fails_for_risk_averse_user() -> None:
    risky_product = replace(BASE_PRODUCT, is_principal_protected=False)
    context = replace(BASE_CONTEXT, product=risky_product, accepts_principal_risk=False)

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_RISK_TOLERANCE" for d in result.failed_decisions)


def test_principal_at_risk_product_passes_when_user_accepts_risk() -> None:
    risky_product = replace(BASE_PRODUCT, is_principal_protected=False)
    context = replace(BASE_CONTEXT, product=risky_product, accepts_principal_risk=True)

    result = evaluate_savings_eligibility(context)

    assert result.eligible is True


def test_deposit_protection_limit_exceeded_fails() -> None:
    context = replace(BASE_CONTEXT, projected_deposit_at_institution=Decimal("60000000"))

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_DEPOSIT_PROTECTION_LIMIT" for d in result.failed_decisions)


def test_deposit_protection_limit_ignored_when_product_not_protected() -> None:
    unprotected_product = replace(BASE_PRODUCT, is_deposit_protected=False)
    context = replace(
        BASE_CONTEXT,
        product=unprotected_product,
        projected_deposit_at_institution=Decimal("999999999"),
    )

    result = evaluate_savings_eligibility(context)

    assert result.eligible is True


def test_preferential_conditions_not_feasible_fails() -> None:
    context = replace(BASE_CONTEXT, preferential_conditions_feasible=False)

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(
        d.rule_code == "SAVINGS_PREFERENTIAL_FEASIBILITY" for d in result.failed_decisions
    )


def test_effective_period_outside_range_fails() -> None:
    context = replace(BASE_CONTEXT, as_of=date(2027, 1, 1))

    result = evaluate_savings_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "SAVINGS_EFFECTIVE_PERIOD" for d in result.failed_decisions)
