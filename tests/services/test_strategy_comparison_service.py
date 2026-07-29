from datetime import date
from decimal import Decimal

import pytest

from app.engines.recommendation import (
    CombinedRecommendationInput,
    DecisionStatus,
    LoanCandidateInput,
    LoanRecommendationInput,
    SavingsAllocationInput,
    SavingsPlanInput,
    SavingsPlanStatus,
    build_combined_recommendation,
)
from app.engines.strategy import HousingCostScenario, StrategyScenarioStatus
from app.engines.stress.models import StressScenarioStatus, StressTestResult
from app.services.strategy_comparison import compare_recommended_purchase_strategies

_AS_OF = date(2026, 7, 30)
_SCENARIOS = (
    HousingCostScenario(
        code="BASE",
        name="기준",
        early_purchase_total_cost=Decimal("300000000"),
        asset_accumulation_total_cost=Decimal("320000000"),
        is_baseline=True,
    ),
)


def _recommendation(*, savings_policy: DecisionStatus = DecisionStatus.PASS):
    loan = LoanRecommendationInput(
        required_amount=Decimal("200000000"),
        months=360,
        annual_income=Decimal("60000000"),
        existing_annual_debt_service=Decimal(0),
        post_purchase_monthly_income=Decimal("5000000"),
        post_purchase_monthly_expense=Decimal("1800000"),
        other_existing_monthly_debt_service=Decimal(0),
        buffer_target=Decimal("300000"),
        safe_dsr=Decimal("0.40"),
        candidates=(
            LoanCandidateInput(
                candidate_id="loan:1",
                product_name="KB 테스트 대출",
                option_name="고정금리",
                maximum_amount=Decimal("200000000"),
                annual_rate=Decimal("0.03"),
                assessment_annual_rate=Decimal("0.03"),
                rate_type_name="고정금리",
                additional_financial_cost=Decimal(0),
                repayment_flexibility_score=Decimal("0.8"),
            ),
        ),
    )
    savings = SavingsPlanInput(
        status=SavingsPlanStatus.COMPLETE,
        policy_status=savings_policy,
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
                source_version="test@2026-07",
            ),
            SavingsAllocationInput(
                candidate_id="savings:2",
                product_name="KB 테스트 예금",
                product_kind="term_deposit",
                institution_name="국민은행",
                allocation_amount=Decimal("10000000"),
                term_months=24,
                maturity_date=date(2028, 7, 30),
                expected_maturity_amount=Decimal("10500000"),
                expected_net_interest=Decimal("500000"),
                product_score=Decimal("75"),
                source_version="test@2026-07",
            ),
        ),
        coverage_ratio=Decimal(1),
        monthly_allocated=Decimal("500000"),
        monthly_unallocated=Decimal(0),
        lump_sum_allocated=Decimal("10000000"),
        lump_sum_unallocated=Decimal(0),
        expected_total_principal=Decimal("16000000"),
        expected_maturity_amount=Decimal("16650000"),
        expected_net_interest=Decimal("650000"),
    )
    return build_combined_recommendation(
        CombinedRecommendationInput(as_of=_AS_OF, loan=loan, savings=savings)
    )


def _stress(*, unknown_count: int = 0) -> StressTestResult:
    return StressTestResult(
        status=(
            StressScenarioStatus.UNKNOWN
            if unknown_count
            else StressScenarioStatus.PASS
        ),
        as_of=_AS_OF,
        scenarios=(),
        pass_count=8 if unknown_count else 9,
        fail_count=0,
        unknown_count=unknown_count,
        pass_ratio=Decimal("0.8") if unknown_count else Decimal(1),
        first_failed_scenario=None,
        maximum_dsr=Decimal("0.3"),
        minimum_buffer_margin=Decimal("100000"),
        maximum_savings_shortfall=Decimal(0),
        scope_notes=(),
    )


def test_service_maps_verified_results_without_double_counting_principal() -> None:
    recommendation = _recommendation()
    result = compare_recommended_purchase_strategies(
        recommendation,
        target_purchase_date=date(2028, 7, 30),
        housing_scenarios=_SCENARIOS,
        early_purchase_equity=Decimal("100000000"),
        additional_accumulation_equity=Decimal("50000000"),
        stress_result=_stress(),
        future_loan_capacity=Decimal("260000000"),
        future_monthly_loan_payment=Decimal("900000"),
        future_total_financial_cost=Decimal("50000000"),
        asset_cashflow_stability_score=Decimal("0.9"),
        asset_plan_flexibility_score=Decimal("0.7"),
        early_plan_flexibility_score=Decimal("0.8"),
    )

    asset = result.asset_accumulation
    early = result.early_purchase
    # 50,000,000 + 전체 만기액 16,650,000이며 예금 원금 10,000,000을 다시 더하지 않는다.
    assert asset.available_equity == Decimal("66650000")
    assert asset.monthly_savings_amount == Decimal("500000")
    assert asset.expected_net_savings_interest == Decimal("650000")
    assert asset.planned_purchase_date == date(2028, 7, 30)
    assert early.loan_capacity == Decimal("200000000")
    assert early.score_components.cashflow_stability == Decimal(1)
    assert early.scenarios[0].status is StrategyScenarioStatus.PASS


def test_unknown_savings_policy_keeps_future_equity_unknown() -> None:
    result = compare_recommended_purchase_strategies(
        _recommendation(savings_policy=DecisionStatus.UNKNOWN),
        target_purchase_date=date(2028, 7, 30),
        housing_scenarios=_SCENARIOS,
        early_purchase_equity=Decimal("100000000"),
        additional_accumulation_equity=Decimal("50000000"),
    )

    assert result.asset_accumulation.available_equity is None
    assert (
        result.asset_accumulation.scenarios[0].status
        is StrategyScenarioStatus.UNKNOWN
    )
    assert "verified_savings_maturity_amount" in result.missing_inputs


def test_unknown_stress_result_does_not_become_a_cashflow_score() -> None:
    result = compare_recommended_purchase_strategies(
        _recommendation(),
        target_purchase_date=date(2028, 7, 30),
        housing_scenarios=_SCENARIOS,
        early_purchase_equity=Decimal("100000000"),
        additional_accumulation_equity=Decimal("50000000"),
        stress_result=_stress(unknown_count=1),
    )

    assert result.early_purchase.score_components.cashflow_stability is None
    assert "early_cashflow_stability_score" in result.missing_inputs


def test_service_rejects_a_different_stress_basis_date() -> None:
    stress = _stress()
    mismatched = StressTestResult(
        **{**stress.__dict__, "as_of": date(2026, 7, 29)}
    )

    with pytest.raises(ValueError, match="기준일"):
        compare_recommended_purchase_strategies(
            _recommendation(),
            target_purchase_date=date(2028, 7, 30),
            housing_scenarios=_SCENARIOS,
            early_purchase_equity=Decimal("100000000"),
            additional_accumulation_equity=Decimal("50000000"),
            stress_result=mismatched,
        )


def test_service_rejects_negative_equity_even_when_savings_is_unknown() -> None:
    with pytest.raises(ValueError, match="additional_accumulation_equity"):
        compare_recommended_purchase_strategies(
            _recommendation(savings_policy=DecisionStatus.UNKNOWN),
            target_purchase_date=date(2028, 7, 30),
            housing_scenarios=_SCENARIOS,
            early_purchase_equity=Decimal("100000000"),
            additional_accumulation_equity=Decimal("-1"),
        )
