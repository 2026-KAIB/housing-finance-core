from datetime import date
from decimal import Decimal

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_credit_loan import KB_CREDIT_LOAN_PACK

REGISTRY = ProductRulePackRegistry((KB_CREDIT_LOAN_PACK,))
AS_OF = date(2026, 7, 25)


def _request(**overrides: object) -> ProductEvaluationRequest:
    facts: dict = {
        "requested_amount": Decimal("350000000"),
        "employment_months": 24,
        "is_overdraft_type": False,
    }
    facts.update(overrides)
    return ProductEvaluationRequest(product_name="KB 신용대출", as_of=AS_OF, facts=facts)


def test_eligible_applicant_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.eligible is True


def test_over_general_limit_fails() -> None:
    result = evaluate_product(_request(requested_amount=Decimal("350000001")), REGISTRY)

    assert result.status is EvaluationStatus.FAIL


def test_short_employment_capped_at_100m() -> None:
    result = evaluate_product(
        _request(employment_months=6, requested_amount=Decimal("100000001")), REGISTRY
    )

    assert result.status is EvaluationStatus.FAIL


def test_overdraft_type_capped_at_150m_even_with_short_employment() -> None:
    result = evaluate_product(
        _request(
            is_overdraft_type=True,
            employment_months=3,
            requested_amount=Decimal("150000000"),
        ),
        REGISTRY,
    )

    assert result.eligible is True
