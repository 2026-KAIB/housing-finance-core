from datetime import date
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.loan_engine_adapter import BorrowerFinancialState
from app.engines.recommendation.engine import build_combined_recommendation
from app.engines.recommendation.models import (
    CombinedRecommendationInput,
    DecisionStatus,
    LoanCandidateInput,
    LoanRecommendationInput,
    SavingsAllocationInput,
    SavingsPlanInput,
    SavingsPlanStatus,
)
from app.engines.stress.models import (
    InterestRateShockApplicability,
    StressScenario,
    StressScenarioKind,
    StressScenarioStatus,
)
from app.regulations.mortgage_limits import HousingStatus, RegulationZone
from app.services.loan_simulation import LoanSimulationRequest
from app.services.stress_simulation import (
    resolve_interest_rate_shock_applicability,
    stress_recommendation,
)

_AS_OF = date(2026, 7, 30)
_BORROWER = BorrowerFinancialState(
    annual_income=Decimal("60000000"),
    existing_annual_debt_service=Decimal("3000000"),
    post_purchase_monthly_income=Decimal("5000000"),
    post_purchase_monthly_expense=Decimal("1800000"),
    other_existing_monthly_debt_service=Decimal("250000"),
    monthly_essential_expense=Decimal("1800000"),
    safe_dsr=Decimal("0.40"),
)
_BASELINE = StressScenario(
    code="BASE",
    name="기준",
    kind=StressScenarioKind.BASELINE,
)
_RATE_UP = StressScenario(
    code="RATE",
    name="금리 1%p 상승",
    kind=StressScenarioKind.INTEREST_RATE,
    interest_rate_increase=Decimal("0.01"),
)


def _loan_request() -> LoanSimulationRequest:
    return LoanSimulationRequest(
        borrower=_BORROWER,
        user_facts={"age": 30},
        house_price=Decimal("600000000"),
        zone=RegulationZone.SPECULATION_OVERHEATED,
        housing_status=HousingStatus.NO_HOUSE,
        is_capital_region=True,
        required_amount=Decimal("100000000"),
        months=360,
        as_of=_AS_OF,
    )


def _loan_input(*, with_candidate: bool = True) -> LoanRecommendationInput:
    candidates = (
        (
            LoanCandidateInput(
                candidate_id="loan:1",
                product_name="KB 테스트 주택담보대출",
                option_name="분할상환 / 변동금리",
                maximum_amount=Decimal("100000000"),
                annual_rate=Decimal("0.03"),
                assessment_annual_rate=Decimal("0.04"),
                rate_type_name="변동금리",
                additional_financial_cost=Decimal(0),
                repayment_flexibility_score=Decimal("0.8"),
            ),
        )
        if with_candidate
        else ()
    )
    return LoanRecommendationInput(
        required_amount=Decimal("100000000"),
        months=360,
        annual_income=_BORROWER.annual_income,
        existing_annual_debt_service=_BORROWER.existing_annual_debt_service,
        post_purchase_monthly_income=_BORROWER.post_purchase_monthly_income,
        post_purchase_monthly_expense=_BORROWER.post_purchase_monthly_expense,
        other_existing_monthly_debt_service=(
            _BORROWER.other_existing_monthly_debt_service
        ),
        buffer_target=_BORROWER.buffer_target,
        safe_dsr=_BORROWER.safe_dsr,
        candidates=candidates,
        unresolved_count=0 if with_candidate else 1,
        missing_inputs=() if with_candidate else ("annual_rate",),
    )


def _savings_input(
    policy_status: DecisionStatus = DecisionStatus.PASS,
) -> SavingsPlanInput:
    return SavingsPlanInput(
        status=SavingsPlanStatus.COMPLETE,
        policy_status=policy_status,
        allocations=(
            SavingsAllocationInput(
                candidate_id="savings:1",
                product_name="KB 테스트 적금",
                product_kind="installment_savings",
                institution_name="국민은행",
                allocation_amount=Decimal("500000"),
                term_months=12,
                maturity_date=date(2027, 7, 30),
                expected_maturity_amount=Decimal("6150000"),
                expected_net_interest=Decimal("150000"),
                product_score=Decimal("80"),
                source_version="test-pack@2026-07",
            ),
        ),
        coverage_ratio=Decimal(1),
        monthly_allocated=Decimal("500000"),
        monthly_unallocated=Decimal(0),
        lump_sum_allocated=Decimal(0),
        lump_sum_unallocated=Decimal(0),
        expected_total_principal=Decimal("6000000"),
        expected_maturity_amount=Decimal("6150000"),
        expected_net_interest=Decimal("150000"),
    )


def _recommendation(
    *,
    with_candidate: bool = True,
    savings_policy_status: DecisionStatus = DecisionStatus.PASS,
):
    return build_combined_recommendation(
        CombinedRecommendationInput(
            as_of=_AS_OF,
            loan=_loan_input(with_candidate=with_candidate),
            savings=_savings_input(savings_policy_status),
        )
    )


def test_service_stresses_the_selected_loan_and_monthly_savings_plan() -> None:
    result = stress_recommendation(
        _recommendation(),
        loan_request=_loan_request(),
        scenarios=(_BASELINE, _RATE_UP),
    )

    assert len(result.scenarios) == 2
    baseline, rate_up = result.scenarios
    assert baseline.monthly_savings_commitment == Decimal("500000")
    assert rate_up.applied_annual_rate == Decimal("0.04")
    assert rate_up.monthly_payment > baseline.monthly_payment
    assert any("추천대출" in note for note in result.scope_notes)


def test_unknown_savings_policy_keeps_savings_maintenance_unknown() -> None:
    result = stress_recommendation(
        _recommendation(savings_policy_status=DecisionStatus.UNKNOWN),
        loan_request=_loan_request(),
        scenarios=(_BASELINE,),
    )

    scenario = result.scenarios[0]
    assert scenario.status is StressScenarioStatus.UNKNOWN
    assert scenario.monthly_savings_commitment is None
    assert "monthly_savings_commitment" in scenario.missing_inputs


def test_missing_recommended_loan_makes_the_plan_stress_unknown() -> None:
    result = stress_recommendation(
        _recommendation(with_candidate=False),
        loan_request=_loan_request(),
        scenarios=(_BASELINE, _RATE_UP),
    )

    assert result.status is StressScenarioStatus.UNKNOWN
    assert result.unknown_count == 2
    assert all(
        scenario.missing_inputs == ("recommended_loan_option",)
        for scenario in result.scenarios
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("변동금리", InterestRateShockApplicability.APPLIES),
        ("고정금리", InterestRateShockApplicability.NOT_APPLIES),
        ("혼합형 고정금리", InterestRateShockApplicability.UNKNOWN),
        (None, InterestRateShockApplicability.UNKNOWN),
    ],
)
def test_rate_type_is_resolved_without_treating_mixed_as_fully_fixed(
    name: str | None,
    expected: InterestRateShockApplicability,
) -> None:
    assert (
        resolve_interest_rate_shock_applicability(
            name,
            loan_principal=Decimal("100000000"),
        )
        is expected
    )


def test_service_rejects_a_different_recommendation_date() -> None:
    recommendation = build_combined_recommendation(
        CombinedRecommendationInput(
            as_of=date(2026, 7, 29),
            loan=_loan_input(),
        )
    )

    with pytest.raises(ValueError, match="기준일"):
        stress_recommendation(
            recommendation,
            loan_request=_loan_request(),
            scenarios=(_BASELINE,),
        )
