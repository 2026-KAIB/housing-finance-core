from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRulePackRegistry,
    evaluate_product,
)
from app.rule_engine.product_packs.packs.kb_star_term_deposit import (
    KB_STAR_TERM_DEPOSIT_PACK,
)

REGISTRY = ProductRulePackRegistry((KB_STAR_TERM_DEPOSIT_PACK,))
AS_OF = date(2026, 7, 24)


def _request(*, deposit_amount: object = 1_000_000, applicant_type: object = "individual"):
    return ProductEvaluationRequest(
        product_name="KB Star 정기예금",
        as_of=AS_OF,
        facts={"deposit_amount": deposit_amount, "applicant_type": applicant_type},
    )


def test_eligible_individual_at_minimum_deposit_passes() -> None:
    result = evaluate_product(_request(), REGISTRY)

    assert result.status is EvaluationStatus.PASS
    assert result.eligible is True


def test_below_minimum_deposit_fails() -> None:
    result = evaluate_product(_request(deposit_amount=999_999), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
    assert any(d.rule_code == "KB_STAR_TD_MIN_DEPOSIT_AMOUNT" for d in result.failed_decisions)


def test_sole_proprietor_passes_membership_rule() -> None:
    result = evaluate_product(_request(applicant_type="sole_proprietor"), REGISTRY)

    assert result.eligible is True


def test_corporation_fails_membership_rule() -> None:
    result = evaluate_product(_request(applicant_type="corporation"), REGISTRY)

    assert result.status is EvaluationStatus.FAIL
    assert any(d.rule_code == "KB_STAR_TD_MEMBER_ELIGIBILITY" for d in result.failed_decisions)


def test_missing_applicant_type_is_unknown_not_fail() -> None:
    result = evaluate_product(_request(applicant_type=None), REGISTRY)

    assert result.status is EvaluationStatus.UNKNOWN
    assert result.eligible is False
    assert result.failed_decisions == ()
    assert any(d.rule_code == "KB_STAR_TD_MEMBER_ELIGIBILITY" for d in result.unknown_decisions)


def test_effective_period_has_no_end_date() -> None:
    far_future = evaluate_product(
        ProductEvaluationRequest(
            product_name="KB Star 정기예금",
            as_of=date(2099, 1, 1),
            facts={"deposit_amount": 1_000_000, "applicant_type": "individual"},
        ),
        REGISTRY,
    )

    assert far_future.eligible is True
