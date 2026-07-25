from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_mortgage_loan import KB_MORTGAGE_LOAN_PACK

REGISTRY = ProductRulePackRegistry((KB_MORTGAGE_LOAN_PACK,))
AS_OF = date(2026, 7, 25)


def _request(loan_term_years: object = 30, age: object = 40) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB 주택담보대출",
        as_of=AS_OF,
        facts={"loan_term_years": loan_term_years, "age": age},
    )


def test_short_term_passes_regardless_of_age() -> None:
    result = evaluate_product(_request(loan_term_years=30, age=50), REGISTRY)

    assert result.eligible is True


def test_long_term_passes_for_young_applicant() -> None:
    result = evaluate_product(_request(loan_term_years=45, age=30), REGISTRY)

    assert result.eligible is True


def test_long_term_fails_for_older_applicant() -> None:
    result = evaluate_product(_request(loan_term_years=45, age=35), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_missing_term_is_unknown() -> None:
    result = evaluate_product(_request(loan_term_years=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
