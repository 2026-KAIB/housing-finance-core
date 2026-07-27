from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_general_installment_savings import (
    KB_GENERAL_INSTALLMENT_SAVINGS_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_GENERAL_INSTALLMENT_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(monthly_payment_amount: object = 10_000) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="일반정기적금",
        as_of=AS_OF,
        facts={"monthly_payment_amount": monthly_payment_amount},
    )


def test_minimum_payment_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_below_minimum_payment_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=9_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_missing_payment_is_unknown() -> None:
    result = evaluate_product(_request(monthly_payment_amount=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
