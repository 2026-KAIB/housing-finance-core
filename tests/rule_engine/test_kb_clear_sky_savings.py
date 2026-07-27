from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_clear_sky_savings import KB_CLEAR_SKY_SAVINGS_PACK

REGISTRY = ProductRulePackRegistry((KB_CLEAR_SKY_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(applicant_type: object = "individual") -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB맑은하늘적금",
        as_of=AS_OF,
        facts={"applicant_type": applicant_type},
    )


def test_eligible_individual_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_sole_proprietor_fails() -> None:
    result = evaluate_product(_request(applicant_type="sole_proprietor"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
