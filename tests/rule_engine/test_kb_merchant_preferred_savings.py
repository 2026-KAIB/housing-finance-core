from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_merchant_preferred_savings import (
    KB_MERCHANT_PREFERRED_SAVINGS_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_MERCHANT_PREFERRED_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(
    age: object = 20,
    is_first_payment: object = True,
    monthly_payment_amount: object = 10_000,
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB가맹점우대적금",
        as_of=AS_OF,
        facts={
            "age": age,
            "is_first_payment": is_first_payment,
            "monthly_payment_amount": monthly_payment_amount,
        },
    )


def test_eligible_first_payment_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_below_minimum_age_fails() -> None:
    result = evaluate_product(_request(age=13), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_first_payment_below_10000_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=9_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_second_payment_of_1000_passes() -> None:
    result = evaluate_product(
        _request(is_first_payment=False, monthly_payment_amount=1_000), REGISTRY
    )

    assert result.eligible is True


def test_payment_above_maximum_fails() -> None:
    result = evaluate_product(
        _request(is_first_payment=False, monthly_payment_amount=10_000_001), REGISTRY
    )

    assert result.status is EvaluationStatus.FAIL
