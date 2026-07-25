from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_freestyle_savings import KB_FREESTYLE_SAVINGS_PACK

REGISTRY = ProductRulePackRegistry((KB_FREESTYLE_SAVINGS_PACK,))
AS_OF = date(2026, 7, 25)


def _request(applicant_type: object = "individual") -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB내맘대로적금",
        as_of=AS_OF,
        facts={"applicant_type": applicant_type},
    )


def test_eligible_sole_proprietor_passes() -> None:
    result = evaluate_product(_request(applicant_type="sole_proprietor"), REGISTRY)

    assert result.eligible is True


def test_corporation_fails() -> None:
    result = evaluate_product(_request(applicant_type="corporation"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_missing_applicant_type_is_unknown() -> None:
    result = evaluate_product(_request(applicant_type=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
