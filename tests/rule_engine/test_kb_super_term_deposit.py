from datetime import date

import pytest

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackNotFoundError,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_super_term_deposit import (
    KB_SUPER_TERM_DEPOSIT_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_SUPER_TERM_DEPOSIT_PACK,))
AS_OF = date(2026, 7, 24)


def _request(*, deposit_amount: object = 1_000_000, as_of: date = AS_OF):
    return ProductEvaluationRequest(
        product_name="국민수퍼정기예금",
        as_of=as_of,
        facts={"deposit_amount": deposit_amount},
    )


def test_eligible_deposit_at_minimum_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.status is EvaluationStatus.PASS
    assert result.eligible is True
    assert result.pack_version == "준법감시인 심의필 제2026-3320-1호"


def test_below_minimum_deposit_fails() -> None:
    result = evaluate_product(_request(deposit_amount=500_000), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
    assert any(d.rule_code == "KB_SUPER_TD_MIN_DEPOSIT_AMOUNT" for d in result.failed_decisions)


def test_missing_deposit_amount_is_unknown_not_fail() -> None:
    result = evaluate_product(_request(deposit_amount=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
    assert result.eligible is False
    assert result.failed_decisions == ()


def test_as_of_outside_effective_period_has_no_active_pack() -> None:
    with pytest.raises(ProductRulePackNotFoundError):
        evaluate_product(_request(as_of=date(2028, 7, 1)), REGISTRY)
