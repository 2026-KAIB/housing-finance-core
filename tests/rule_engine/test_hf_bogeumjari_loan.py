from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.hf_bogeumjari_loan import HF_BOGEUMJARI_LOAN_PACK

REGISTRY = ProductRulePackRegistry((HF_BOGEUMJARI_LOAN_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {
        "age": 35,
        "owns_house": False,
        "combined_annual_income": Decimal("60000000"),
        "child_count": 0,
        "is_newlywed": False,
        "requested_amount": Decimal("300000000"),
        "is_first_home_buyer": False,
        "is_multi_child_or_jeonse_fraud_victim": False,
    }
    facts.update(overrides)
    return ProductEvaluationRequest(
        product_name="한국주택금융공사 아낌e-보금자리론", as_of=AS_OF, facts=facts
    )


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_house_owner_fails() -> None:
    result = evaluate_product(_request(owns_house=True), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_income_over_default_limit_fails() -> None:
    result = evaluate_product(_request(combined_annual_income=Decimal("70000001")), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_income_within_multi_child_limit_passes() -> None:
    result = evaluate_product(
        _request(combined_annual_income=Decimal("95000000"), child_count=2), REGISTRY
    )

    assert result.eligible is True


def test_loan_amount_over_default_limit_fails() -> None:
    result = evaluate_product(_request(requested_amount=Decimal("360000001")), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_loan_amount_within_first_home_buyer_limit_passes() -> None:
    result = evaluate_product(
        _request(requested_amount=Decimal("420000000"), is_first_home_buyer=True), REGISTRY
    )

    assert result.eligible is True
