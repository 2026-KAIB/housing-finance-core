from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_salary_credit_loan import (
    KB_SALARY_CREDIT_LOAN_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_SALARY_CREDIT_LOAN_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {
        "employment_months": 12,
        "salary_transfer_count": 1,
        "is_sole_proprietor": False,
        "is_pension_transfer_recipient": False,
        "requested_amount": Decimal("150000000"),
        "is_overdraft_type": False,
    }
    facts.update(overrides)
    return ProductEvaluationRequest(product_name="KB 급여이체신용대출", as_of=AS_OF, facts=facts)


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_short_employment_fails() -> None:
    result = evaluate_product(_request(employment_months=11), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_no_salary_transfer_record_fails() -> None:
    result = evaluate_product(_request(salary_transfer_count=0), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_sole_proprietor_fails() -> None:
    result = evaluate_product(_request(is_sole_proprietor=True), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_overdraft_type_capped_at_100m() -> None:
    result = evaluate_product(
        _request(is_overdraft_type=True, requested_amount=Decimal("100000001")), REGISTRY
    )

    assert result.status is EvaluationStatus.FAIL


def test_amount_between_100m_and_150m_without_overdraft_info_is_unknown() -> None:
    result = evaluate_product(
        _request(is_overdraft_type=None, requested_amount=Decimal("120000000")), REGISTRY
    )

    assert result.status is EvaluationStatus.UNKNOWN


def test_amount_at_100m_passes_even_without_overdraft_info() -> None:
    result = evaluate_product(
        _request(is_overdraft_type=None, requested_amount=Decimal("100000000")), REGISTRY
    )

    assert result.eligible is True
