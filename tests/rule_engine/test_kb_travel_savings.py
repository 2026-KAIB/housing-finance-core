from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_travel_savings import KB_TRAVEL_SAVINGS_PACK

REGISTRY = ProductRulePackRegistry((KB_TRAVEL_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(
    applicant_type: object = "individual", monthly_payment_amount: object = 50_000
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB 두근두근여행적금",
        as_of=AS_OF,
        facts={
            "applicant_type": applicant_type,
            "monthly_payment_amount": monthly_payment_amount,
        },
    )


def test_eligible_individual_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_sole_proprietor_fails() -> None:
    result = evaluate_product(_request(applicant_type="sole_proprietor"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_payment_below_minimum_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=49_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
