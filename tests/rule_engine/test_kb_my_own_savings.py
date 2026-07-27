from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_my_own_savings import KB_MY_OWN_SAVINGS_PACK

REGISTRY = ProductRulePackRegistry((KB_MY_OWN_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(
    applicant_type: object = "individual", monthly_payment_amount: object = 500_000
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB 나만의 적금",
        as_of=AS_OF,
        facts={
            "applicant_type": applicant_type,
            "monthly_payment_amount": monthly_payment_amount,
        },
    )


def test_eligible_unincorporated_association_passes() -> None:
    result = evaluate_product(_request(applicant_type="unincorporated_association"), REGISTRY)

    assert result.eligible is True


def test_corporation_fails_member_rule() -> None:
    result = evaluate_product(_request(applicant_type="corporation"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_payment_above_range_fails() -> None:
    result = evaluate_product(_request(monthly_payment_amount=1_000_001), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
