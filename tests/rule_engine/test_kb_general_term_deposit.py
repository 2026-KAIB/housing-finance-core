from datetime import date

import pytest

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackNotFoundError,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_general_term_deposit import (
    KB_GENERAL_TERM_DEPOSIT_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_GENERAL_TERM_DEPOSIT_PACK,))
AS_OF = date(2026, 7, 24)


def _request(
    *,
    deposit_amount: object = 100_000,
    as_of: date = AS_OF,
) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name="일반정기예금",
        as_of=as_of,
        facts={"deposit_amount": deposit_amount},
    )


def test_minimum_deposit_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.status is EvaluationStatus.PASS
    assert result.pack_version == "준법감시인 심의필 제2026-3320-2호"


def test_below_minimum_deposit_fails() -> None:
    result = evaluate_product(_request(deposit_amount=99_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
    assert result.failed_decisions[0].rule_code == (
        "KB_GENERAL_TD_MIN_DEPOSIT_AMOUNT"
    )


def test_missing_deposit_amount_is_unknown_not_fail() -> None:
    result = evaluate_product(_request(deposit_amount=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
    assert result.failed_decisions == ()
    assert result.unknown_decisions[0].rule_code == (
        "KB_GENERAL_TD_MIN_DEPOSIT_AMOUNT"
    )


def test_as_of_outside_document_effective_period_has_no_pack() -> None:
    with pytest.raises(ProductRulePackNotFoundError):
        evaluate_product(_request(as_of=date(2028, 7, 1)), REGISTRY)
