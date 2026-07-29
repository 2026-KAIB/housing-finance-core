from datetime import date
from decimal import Decimal

import pytest

from app.engines.recommendation.engine import (
    build_combined_recommendation,
    recommend_loans,
    recommend_savings,
)
from app.engines.recommendation.models import (
    CombinedRecommendationInput,
    ComponentStatus,
    DecisionStatus,
    LoanCandidateInput,
    LoanRecommendationInput,
    RecommendationPolicy,
    RecommendationStatus,
    SavingsAllocationInput,
    SavingsPlanInput,
    SavingsPlanStatus,
    ScoreStatus,
)

_AS_OF = date(2026, 7, 30)


def _candidate(
    candidate_id: str,
    *,
    product_name: str | None = None,
    maximum_amount: str = "300000000",
    annual_rate: str = "0.035",
    assessment_annual_rate: str | None = "0.045",
    additional_financial_cost: str | None = "0",
    repayment_flexibility_score: str | None = "0.8",
    assumptions: tuple[str, ...] = (),
) -> LoanCandidateInput:
    return LoanCandidateInput(
        candidate_id=candidate_id,
        product_name=product_name or candidate_id,
        option_name="분할상환 / 고정금리",
        maximum_amount=Decimal(maximum_amount),
        annual_rate=Decimal(annual_rate),
        assessment_annual_rate=(
            None
            if assessment_annual_rate is None
            else Decimal(assessment_annual_rate)
        ),
        additional_financial_cost=(
            None
            if additional_financial_cost is None
            else Decimal(additional_financial_cost)
        ),
        repayment_flexibility_score=(
            None
            if repayment_flexibility_score is None
            else Decimal(repayment_flexibility_score)
        ),
        assumptions=assumptions,
    )


def _loan_input(
    *candidates: LoanCandidateInput,
    required_amount: str = "300000000",
    missing_inputs: tuple[str, ...] = (),
    unresolved_count: int = 0,
) -> LoanRecommendationInput:
    return LoanRecommendationInput(
        required_amount=Decimal(required_amount),
        months=360,
        annual_income=Decimal("60000000"),
        existing_annual_debt_service=Decimal("3000000"),
        post_purchase_monthly_income=Decimal("5000000"),
        post_purchase_monthly_expense=Decimal("1800000"),
        other_existing_monthly_debt_service=Decimal("250000"),
        buffer_target=Decimal("300000"),
        safe_dsr=Decimal("0.40"),
        candidates=tuple(candidates),
        unresolved_count=unresolved_count,
        missing_inputs=missing_inputs,
        policy_sources=("2026-07 대출정책",),
    )


def _allocation() -> SavingsAllocationInput:
    return SavingsAllocationInput(
        candidate_id="savings:1",
        product_name="KB 테스트 정기예금",
        product_kind="term_deposit",
        institution_name="국민은행",
        allocation_amount=Decimal("10000000"),
        term_months=12,
        maturity_date=date(2027, 7, 30),
        expected_maturity_amount=Decimal("10300000"),
        expected_net_interest=Decimal("300000"),
        product_score=Decimal("82"),
        source_version="test-pack@2026-07",
    )


def _savings(
    *,
    policy_status: DecisionStatus = DecisionStatus.PASS,
    status: SavingsPlanStatus = SavingsPlanStatus.COMPLETE,
    missing_inputs: tuple[str, ...] = (),
) -> SavingsPlanInput:
    return SavingsPlanInput(
        status=status,
        policy_status=policy_status,
        allocations=(_allocation(),),
        coverage_ratio=Decimal(1),
        monthly_allocated=Decimal(0),
        monthly_unallocated=Decimal(0),
        lump_sum_allocated=Decimal("10000000"),
        lump_sum_unallocated=Decimal(0),
        expected_total_principal=Decimal("10000000"),
        expected_maturity_amount=Decimal("10300000"),
        expected_net_interest=Decimal("300000"),
        missing_inputs=missing_inputs,
    )


def test_complete_candidates_are_ranked_by_the_official_mcda_components() -> None:
    cheaper = _candidate("cheap", annual_rate="0.03", assessment_annual_rate="0.04")
    expensive = _candidate("expensive", annual_rate="0.05", assessment_annual_rate="0.06")

    result = recommend_loans(
        _loan_input(expensive, cheaper),
        policy=RecommendationPolicy(),
    )

    assert result.status is ComponentStatus.READY
    assert result.primary is not None
    assert result.primary.candidate_id == "cheap"
    assert result.primary.score_status is ScoreStatus.COMPLETE
    assert result.primary.score_completeness == Decimal(1)
    assert result.primary.recommended_amount == Decimal("300000000")
    assert result.primary.recommended_amount <= result.primary.maximum_amount
    assert result.primary.score > result.alternatives[0].score


def test_recommendation_never_increases_a_partial_loan_to_the_requested_amount() -> None:
    result = recommend_loans(
        _loan_input(
            _candidate("partial", maximum_amount="200000000"),
        ),
        policy=RecommendationPolicy(),
    )

    assert result.status is ComponentStatus.PARTIAL
    assert result.primary is not None
    assert result.primary.recommended_amount == Decimal("200000000")
    assert result.primary.funding_shortfall == Decimal("100000000")
    assert not result.primary.covers_required_amount


def test_missing_cost_and_flexibility_are_not_silently_scored_as_zero() -> None:
    provisional = _candidate(
        "provisional",
        additional_financial_cost=None,
        repayment_flexibility_score=None,
    )

    result = build_combined_recommendation(
        CombinedRecommendationInput(
            as_of=_AS_OF,
            loan=_loan_input(provisional),
        )
    )

    assert result.status is RecommendationStatus.NEEDS_REVIEW
    assert result.loan.primary is not None
    assert result.loan.primary.score_status is ScoreStatus.PROVISIONAL
    assert result.loan.primary.score_completeness == Decimal("0.65")
    assert set(result.loan.primary.missing_score_components) == {
        "total_cost",
        "repayment_flexibility",
    }
    assert result.loan.primary.score_components.total_cost is None
    assert result.loan.primary.score_components.repayment_flexibility is None


def test_unknown_loan_inputs_remain_unknown_instead_of_becoming_zero_capacity() -> None:
    result = build_combined_recommendation(
        CombinedRecommendationInput(
            as_of=_AS_OF,
            loan=_loan_input(
                missing_inputs=("stress_dsr_rate",),
                unresolved_count=1,
            ),
        )
    )

    assert result.status is RecommendationStatus.NEEDS_REVIEW
    assert result.loan.status is ComponentStatus.UNKNOWN
    assert result.loan.maximum_recommendable_amount == 0
    assert result.missing_inputs == ("stress_dsr_rate",)


def test_unverified_savings_allocations_are_not_forwarded_as_recommendations() -> None:
    summary = recommend_savings(
        _savings(
            policy_status=DecisionStatus.UNKNOWN,
            missing_inputs=("savings_policy_validation",),
        )
    )

    assert summary.status is ComponentStatus.UNKNOWN
    assert summary.allocations == ()
    assert summary.missing_inputs == ("savings_policy_validation",)


def test_complete_loan_and_verified_savings_make_a_complete_combined_result() -> None:
    result = build_combined_recommendation(
        CombinedRecommendationInput(
            as_of=_AS_OF,
            loan=_loan_input(_candidate("loan")),
            savings=_savings(),
        )
    )

    assert result.status is RecommendationStatus.COMPLETE
    assert result.loan.status is ComponentStatus.READY
    assert result.savings.status is ComponentStatus.READY
    assert result.savings.allocations[0].product_name == "KB 테스트 정기예금"
    assert result.as_of == _AS_OF
    assert result.disclaimers


def test_policy_rejects_weights_that_do_not_sum_to_one() -> None:
    with pytest.raises(ValueError, match="가중치 합은 1"):
        RecommendationPolicy(repayment_capacity_weight=Decimal("0.20"))
