from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_star_jeonse_loan_hf import (
    KB_STAR_JEONSE_LOAN_HF_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_STAR_JEONSE_LOAN_HF_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {
        "age": 30,
        "is_household_head": True,
        "owned_house_count": 0,
        "lease_deposit": Decimal("300000000"),
        "is_capital_region": True,
        "requested_amount": Decimal("200000000"),
        "is_newlywed_or_multi_child": False,
    }
    facts.update(overrides)
    return ProductEvaluationRequest(
        product_name="KB스타 전세자금대출(HF_한국주택금융공사)", as_of=AS_OF, facts=facts
    )


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_general_amount_up_to_222m_passes() -> None:
    result = evaluate_product(_request(requested_amount=Decimal("222000000")), REGISTRY)

    assert result.eligible is True


def test_general_amount_over_222m_fails() -> None:
    result = evaluate_product(_request(requested_amount=Decimal("222000001")), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_newlywed_amount_capped_at_200m() -> None:
    result = evaluate_product(
        _request(is_newlywed_or_multi_child=True, requested_amount=Decimal("200000001")),
        REGISTRY,
    )

    assert result.status is EvaluationStatus.FAIL


def test_underage_applicant_fails() -> None:
    result = evaluate_product(_request(age=18), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_amount_between_200m_and_222m_without_newlywed_info_is_unknown() -> None:
    result = evaluate_product(
        _request(requested_amount=Decimal("210000000"), is_newlywed_or_multi_child=None),
        REGISTRY,
    )

    assert result.status is EvaluationStatus.UNKNOWN


def test_amount_at_200m_passes_even_without_newlywed_info() -> None:
    result = evaluate_product(
        _request(requested_amount=Decimal("200000000"), is_newlywed_or_multi_child=None),
        REGISTRY,
    )

    assert result.eligible is True
