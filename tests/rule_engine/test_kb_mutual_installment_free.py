from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_mutual_installment_free import (
    KB_MUTUAL_INSTALLMENT_FREE_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_MUTUAL_INSTALLMENT_FREE_PACK,))
AS_OF = date(2026, 7, 25)


def _request(monthly_payment_amount: object = 10_000) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB상호부금(자유적립식)",
        as_of=AS_OF,
        facts={"monthly_payment_amount": monthly_payment_amount},
    )


def test_within_range_passes() -> None:
    result = evaluate_product(_request(monthly_payment_amount=5_000_000), REGISTRY)

    assert result.eligible is True


def test_above_range_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=5_000_001), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
