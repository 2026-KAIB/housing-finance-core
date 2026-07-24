from datetime import date

import pytest

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackNotFoundError,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_golden_life_pension_deposit import (
    KB_GOLDEN_LIFE_PENSION_DEPOSIT_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_GOLDEN_LIFE_PENSION_DEPOSIT_PACK,))
AS_OF = date(2026, 7, 24)


def _request(
    *,
    deposit_amount: object = 1_000_000,
    applicant_type: object = "individual",
    as_of: date = AS_OF,
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="KB골든라이프연금예금",
        as_of=as_of,
        facts={
            "deposit_amount": deposit_amount,
            "applicant_type": applicant_type,
        },
    )


def test_eligible_individual_at_minimum_deposit_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.status is EvaluationStatus.PASS
    assert result.pack_version == "준법감시인 심의필 제2026-3320-4호"


@pytest.mark.parametrize(
    "applicant_type",
    ["sole_proprietor", "unincorporated_association"],
)
def test_explicitly_allowed_non_individual_member_types_pass(
    applicant_type: str,
) -> None:
    result = evaluate_product(_request(applicant_type=applicant_type), REGISTRY)

    assert result.eligible is True


def test_below_minimum_deposit_fails() -> None:
    result = evaluate_product(_request(deposit_amount=999_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
    assert result.failed_decisions[0].rule_code == (
        "KB_GOLDEN_LIFE_PD_MIN_DEPOSIT_AMOUNT"
    )


def test_corporation_fails_member_eligibility() -> None:
    result = evaluate_product(_request(applicant_type="corporation"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
    assert any(
        decision.rule_code == "KB_GOLDEN_LIFE_PD_MEMBER_ELIGIBILITY"
        for decision in result.failed_decisions
    )


def test_missing_member_type_is_unknown_not_fail() -> None:
    result = evaluate_product(_request(applicant_type=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
    assert result.failed_decisions == ()
    assert result.unknown_decisions[0].rule_code == (
        "KB_GOLDEN_LIFE_PD_MEMBER_ELIGIBILITY"
    )


def test_as_of_outside_document_effective_period_has_no_pack() -> None:
    with pytest.raises(ProductRulePackNotFoundError):
        evaluate_product(_request(as_of=date(2028, 7, 1)), REGISTRY)
