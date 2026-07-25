from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_mutual_installment_fixed import (
    KB_MUTUAL_INSTALLMENT_FIXED_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_MUTUAL_INSTALLMENT_FIXED_PACK,))
AS_OF = date(2026, 7, 25)


def _request(monthly_payment_amount: object = 10_000) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB상호부금(정액적립식)",
        as_of=AS_OF,
        facts={"monthly_payment_amount": monthly_payment_amount},
    )


def test_minimum_payment_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_below_minimum_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=9_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
