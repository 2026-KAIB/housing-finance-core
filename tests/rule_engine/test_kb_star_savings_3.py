from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_star_savings_3 import KB_STAR_SAVINGS_3_PACK

REGISTRY = ProductRulePackRegistry((KB_STAR_SAVINGS_3_PACK,))
AS_OF = date(2026, 7, 25)


def _request(
    age: object = 20,
    applicant_type: object = "individual",
    monthly_payment_amount: object = 100_000,
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB 스타적금 III",
        as_of=AS_OF,
        facts={
            "age": age,
            "applicant_type": applicant_type,
            "monthly_payment_amount": monthly_payment_amount,
        },
    )


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_below_minimum_age_fails() -> None:
    result = evaluate_product(_request(age=18), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_sole_proprietor_fails() -> None:
    result = evaluate_product(_request(applicant_type="sole_proprietor"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_payment_above_range_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=300_001), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
