from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_star_jeonse_loan_hug import (
    KB_STAR_JEONSE_LOAN_HUG_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_STAR_JEONSE_LOAN_HUG_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {
        "age": 30,
        "is_household_head": True,
        "owned_house_count": 0,
        "lease_deposit": Decimal("300000000"),
        "is_capital_region": True,
        "requested_amount": Decimal("200000000"),
    }
    facts.update(overrides)
    return ProductEvaluationRequest(
        product_name="KB스타 전세자금대출(HUG_주택도시보증공사)", as_of=AS_OF, facts=facts
    )


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_not_household_head_fails() -> None:
    result = evaluate_product(_request(is_household_head=False), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_two_houses_owned_fails() -> None:
    result = evaluate_product(_request(owned_house_count=2), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_deposit_over_capital_region_cap_fails() -> None:
    result = evaluate_product(
        _request(lease_deposit=Decimal("700000001"), is_capital_region=True), REGISTRY
    )

    assert result.status is EvaluationStatus.FAIL


def test_deposit_within_non_capital_region_cap_passes() -> None:
    result = evaluate_product(
        _request(lease_deposit=Decimal("500000000"), is_capital_region=False), REGISTRY
    )

    assert result.eligible is True


def test_one_house_owner_capped_at_200m() -> None:
    result = evaluate_product(
        _request(owned_house_count=1, requested_amount=Decimal("200000001")), REGISTRY
    )

    assert result.status is EvaluationStatus.FAIL
