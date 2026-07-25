from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_emergency_cash_loan import (
    KB_EMERGENCY_CASH_LOAN_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_EMERGENCY_CASH_LOAN_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {"age": 25, "is_foreigner": False, "requested_amount": 1_000_000}
    facts.update(overrides)
    return ProductEvaluationRequest(product_name="KB 비상금대출", as_of=AS_OF, facts=facts)


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_underage_applicant_fails() -> None:
    result = evaluate_product(_request(age=18), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_foreigner_fails() -> None:
    result = evaluate_product(_request(is_foreigner=True), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_amount_over_maximum_fails() -> None:
    result = evaluate_product(_request(requested_amount=3_000_001), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_amount_below_minimum_fails() -> None:
    result = evaluate_product(_request(requested_amount=499_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
