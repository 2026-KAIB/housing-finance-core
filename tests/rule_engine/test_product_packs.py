from datetime import date

import pytest

from app.rule_engine.product_packs import (
    ComparisonOperator,
    ComparisonRule,
    EvaluationStatus,
    ProductCategory,
    ProductEvaluationRequest,
    ProductRulePack,
    ProductRulePackNotFoundError,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.example_product import EXAMPLE_PRODUCT_PACK


def _pack(
    *,
    version: str = "v1",
    start: date = date(2026, 1, 1),
    end: date | None = None,
) -> ProductRulePack:
    return ProductRulePack(
        product_name="테스트 신용대출",
        aliases=("테스트론",),
        category=ProductCategory.CREDIT_LOAN,
        version=version,
        effective_start_date=start,
        effective_end_date=end,
        source_url="https://example.invalid/test",
        rules=(
            ComparisonRule(
                code="MIN_AGE",
                field_name="age",
                operator=ComparisonOperator.GTE,
                expected=19,
                failure_reason="만 19세 이상이어야 합니다.",
            ),
        ),
    )


def _request(product_name: str = "테스트 신용대출", age: object = 30) -> ProductEvaluationRequest:
    return ProductEvaluationRequest(
        product_name=product_name,
        as_of=date(2026, 7, 24),
        facts={"age": age},
    )


def test_evaluate_product_passes_with_canonical_name() -> None:
    registry = ProductRulePackRegistry((_pack(),))

    result = evaluate_product(_request(), registry)

    assert result.status is EvaluationStatus.PASS
    assert result.eligible is True
    assert result.product_name == "테스트 신용대출"
    assert result.pack_version == "v1"


def test_registry_resolves_normalized_alias() -> None:
    registry = ProductRulePackRegistry((_pack(),))

    result = evaluate_product(_request(product_name="  테스트론  "), registry)

    assert result.status is EvaluationStatus.PASS
    assert result.requested_product_name == "  테스트론  "
    assert result.product_name == "테스트 신용대출"


def test_evaluate_product_fails_and_keeps_reason() -> None:
    registry = ProductRulePackRegistry((_pack(),))

    result = evaluate_product(_request(age=18), registry)

    assert result.status is EvaluationStatus.FAIL
    assert result.eligible is False
    assert result.failed_decisions[0].rule_code == "MIN_AGE"
    assert result.failed_decisions[0].reasons == ("만 19세 이상이어야 합니다.",)


def test_missing_fact_is_unknown_instead_of_fail() -> None:
    registry = ProductRulePackRegistry((_pack(),))
    request = ProductEvaluationRequest(
        product_name="테스트 신용대출",
        as_of=date(2026, 7, 24),
        facts={},
    )

    result = evaluate_product(request, registry)

    assert result.status is EvaluationStatus.UNKNOWN
    assert result.eligible is False
    assert result.failed_decisions == ()
    assert result.unknown_decisions[0].rule_code == "MIN_AGE"


def test_registry_selects_pack_version_by_as_of_date() -> None:
    old_pack = _pack(version="v1", start=date(2026, 1, 1), end=date(2026, 6, 30))
    new_pack = _pack(version="v2", start=date(2026, 7, 1))
    registry = ProductRulePackRegistry((old_pack, new_pack))

    result = evaluate_product(_request(), registry)

    assert result.pack_version == "v2"


def test_registry_rejects_overlapping_versions() -> None:
    registry = ProductRulePackRegistry((_pack(),))

    with pytest.raises(ValueError, match="적용기간이 겹치는"):
        registry.register(_pack(version="v2"))


def test_unknown_product_name_is_not_fuzzily_matched() -> None:
    registry = ProductRulePackRegistry((_pack(),))

    with pytest.raises(ProductRulePackNotFoundError, match="등록된"):
        evaluate_product(_request(product_name="테스트 신용 대출"), registry)


def test_pack_cannot_be_registered_without_rules() -> None:
    with pytest.raises(ValueError, match="자동 PASS"):
        ProductRulePack(
            product_name="빈 상품",
            category=ProductCategory.TERM_DEPOSIT,
            version="v1",
            effective_start_date=date(2026, 1, 1),
            effective_end_date=None,
            rules=(),
        )


def test_product_specific_predicate_can_evaluate_compound_condition() -> None:
    registry = ProductRulePackRegistry((EXAMPLE_PRODUCT_PACK,))
    request = ProductEvaluationRequest(
        product_name="__개발예시 신용대출__",
        as_of=date(2026, 7, 24),
        facts={"age": 30, "annual_income": 40_000_000},
    )

    result = evaluate_product(request, registry)

    assert result.status is EvaluationStatus.PASS


def test_fail_takes_precedence_over_unknown_when_aggregating() -> None:
    registry = ProductRulePackRegistry((EXAMPLE_PRODUCT_PACK,))
    request = ProductEvaluationRequest(
        product_name="__개발예시 신용대출__",
        as_of=date(2026, 7, 24),
        facts={"age": 18},
    )

    result = evaluate_product(request, registry)

    assert result.status is EvaluationStatus.FAIL
    assert [decision.status for decision in result.decisions] == [
        EvaluationStatus.FAIL,
        EvaluationStatus.UNKNOWN,
    ]
