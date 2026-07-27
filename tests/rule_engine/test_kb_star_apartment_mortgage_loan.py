from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_star_apartment_mortgage_loan import (
    KB_STAR_APARTMENT_MORTGAGE_LOAN_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_STAR_APARTMENT_MORTGAGE_LOAN_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {
        "age": 30,
        "is_foreigner": False,
        "requested_amount": 500_000_000,
        "loan_term_years": 30,
    }
    facts.update(overrides)
    return ProductEvaluationRequest(
        product_name="KB스타 아파트담보대출(주택자금)", as_of=AS_OF, facts=facts
    )


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_minor_fails() -> None:
    result = evaluate_product(_request(age=18), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_foreigner_fails() -> None:
    result = evaluate_product(_request(is_foreigner=True), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_amount_out_of_range_fails() -> None:
    result = evaluate_product(_request(requested_amount=9_999_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_long_term_fails_for_older_applicant() -> None:
    result = evaluate_product(_request(loan_term_years=45, age=35), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
