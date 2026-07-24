from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.rule_engine.common import ApplicantEligibilityCriteria, ApplicantSnapshot
from app.rule_engine.loans import LoanEligibilityContext, LoanProduct, evaluate_loan_eligibility

AS_OF = date(2026, 7, 23)

BASE_PRODUCT = LoanProduct(
    product_id="bank-mortgage-01",
    name="주택담보대출(placeholder)",
    operating_institution="샘플은행",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    confirmed_date=date(2026, 7, 1),
    source_url="https://example.bank/mortgage",
    eligibility=ApplicantEligibilityCriteria(),
    loan_limit=Decimal("500000000"),
    max_ltv=Decimal("0.70"),
    max_dti=Decimal("0.60"),
    max_dsr=Decimal("0.40"),
)

BASE_APPLICANT = ApplicantSnapshot(
    age=35,
    annual_income=Decimal("60000000"),
    is_married=True,
    is_first_home_buyer=True,
    region_code="11",
    target_price=Decimal("500000000"),
    target_area_m2=Decimal("59"),
)

BASE_CONTEXT = LoanEligibilityContext(
    as_of=AS_OF,
    applicant=BASE_APPLICANT,
    product=BASE_PRODUCT,
    requested_loan_amount=Decimal("300000000"),
    computed_ltv=Decimal("0.60"),
    computed_dti=Decimal("0.50"),
    computed_dsr=Decimal("0.3694"),
    equity_available=Decimal("200000000"),
    equity_target=Decimal("200000000"),
    buffer_target=Decimal("300000"),
    post_purchase_monthly_cashflow=Decimal("500000"),
    post_purchase_emergency_fund=Decimal("5000000"),
)


def test_fully_eligible_loan_passes_every_rule() -> None:
    result = evaluate_loan_eligibility(BASE_CONTEXT)

    assert result.eligible is True
    assert result.reasons == ()


def test_requested_amount_over_product_limit_fails() -> None:
    context = replace(BASE_CONTEXT, requested_loan_amount=Decimal("600000000"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "LOAN_PRODUCT_LIMIT" for d in result.failed_decisions)


def test_ltv_over_limit_fails() -> None:
    context = replace(BASE_CONTEXT, computed_ltv=Decimal("0.71"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "LOAN_LTV_LIMIT" for d in result.failed_decisions)


def test_ltv_at_exact_limit_passes() -> None:
    context = replace(BASE_CONTEXT, computed_ltv=BASE_PRODUCT.max_ltv)

    result = evaluate_loan_eligibility(context)

    assert result.eligible is True


def test_dti_over_limit_fails() -> None:
    context = replace(BASE_CONTEXT, computed_dti=Decimal("0.61"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "LOAN_DTI_LIMIT" for d in result.failed_decisions)


def test_dsr_over_limit_fails() -> None:
    context = replace(BASE_CONTEXT, computed_dsr=Decimal("0.41"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "LOAN_DSR_LIMIT" for d in result.failed_decisions)


def test_insufficient_equity_fails_with_shortfall_reason() -> None:
    context = replace(
        BASE_CONTEXT, equity_available=Decimal("150000000"), equity_target=Decimal("200000000")
    )

    result = evaluate_loan_eligibility(context)

    decision = next(d for d in result.decisions if d.rule_code == "LOAN_EQUITY_ADEQUACY")
    assert decision.passed is False
    assert "50000000" in decision.reasons[0]


def test_negative_post_purchase_emergency_fund_fails() -> None:
    context = replace(BASE_CONTEXT, post_purchase_emergency_fund=Decimal("-1"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is False
    assert any(d.rule_code == "LOAN_POST_PURCHASE_EMERGENCY_FUND" for d in result.failed_decisions)


def test_zero_post_purchase_emergency_fund_passes() -> None:
    context = replace(BASE_CONTEXT, post_purchase_emergency_fund=Decimal("0"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is True


def test_post_purchase_cashflow_below_buffer_fails() -> None:
    context = replace(BASE_CONTEXT, post_purchase_monthly_cashflow=Decimal("299999"))

    result = evaluate_loan_eligibility(context)

    assert result.eligible is False
    assert any(
        d.rule_code == "LOAN_POST_PURCHASE_CASHFLOW_BUFFER" for d in result.failed_decisions
    )


def test_dsr_limit_uses_dsr_that_already_includes_existing_and_new_debt() -> None:
    # DESIGN SSOT A-11 골든 케이스: 연소득 6천만, 기존 600만/년, 신규 PMT 16,165,609/년 -> 0.3694
    context = replace(
        BASE_CONTEXT,
        applicant=replace(BASE_APPLICANT, annual_income=Decimal("60000000")),
        computed_dsr=Decimal("0.3694"),
    )

    result = evaluate_loan_eligibility(context)
    decision = next(d for d in result.decisions if d.rule_code == "LOAN_DSR_LIMIT")

    assert decision.passed is True
