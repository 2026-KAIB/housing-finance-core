from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_premium_installment_savings import (
    KB_PREMIUM_INSTALLMENT_SAVINGS_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_PREMIUM_INSTALLMENT_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(
    applicant_type: object = "individual", monthly_payment_amount: object = 1_000_000
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB 국민프리미엄적금",
        as_of=AS_OF,
        facts={
            "applicant_type": applicant_type,
            "monthly_payment_amount": monthly_payment_amount,
        },
    )


def test_eligible_individual_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_sole_proprietor_fails_member_rule() -> None:
    result = evaluate_product(_request(applicant_type="sole_proprietor"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_payment_above_range_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=3_000_001), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_payment_below_range_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=9_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
