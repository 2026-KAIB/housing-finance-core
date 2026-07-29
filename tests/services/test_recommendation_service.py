"""서비스 조립 계층이 대출·예적금 결과의 근거와 결측을 보존하는지 검증한다."""

from datetime import date
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.loan_engine_adapter import (
    BorrowerFinancialState,
    LoanComputation,
)
from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    SavingsPortfolioPolicyValidation,
)
from app.data_pipeline.normalizers.loan_product import NormalizedLoanOption
from app.engines.recommendation.models import (
    ComponentStatus,
    RecommendationStatus,
    ScoreStatus,
)
from app.engines.savings.models import SavingsProductKind
from app.engines.savings.portfolio_models import (
    PortfolioAllocationBasis,
    SavingsPortfolioAllocation,
    SavingsPortfolioResult,
    SavingsPortfolioStatus,
)
from app.regulations.mortgage_limits import HousingStatus, RegulationZone
from app.rule_engine.product_packs.models import EvaluationStatus
from app.services.loan_simulation import LoanSimulationRequest, LoanSimulationResult
from app.services.recommendation import (
    LoanRecommendationSupplement,
    recommend_from_results,
)

_AS_OF = date(2026, 7, 30)
_OPTION = NormalizedLoanOption(
    product_name="KB 테스트 주택담보대출",
    mortgage_type_name="아파트",
    repayment_type_name="분할상환",
    rate_type_name="고정금리",
    annual_rate_min=Decimal("0.03"),
    annual_rate_max=Decimal("0.04"),
    annual_rate_avg=Decimal("0.035"),
)
_BORROWER = BorrowerFinancialState(
    annual_income=Decimal("60000000"),
    existing_annual_debt_service=Decimal("3000000"),
    post_purchase_monthly_income=Decimal("5000000"),
    post_purchase_monthly_expense=Decimal("1800000"),
    other_existing_monthly_debt_service=Decimal("250000"),
    monthly_essential_expense=Decimal("1800000"),
    safe_dsr=Decimal("0.40"),
)


def _loan_request() -> LoanSimulationRequest:
    return LoanSimulationRequest(
        borrower=_BORROWER,
        user_facts={"age": 30},
        house_price=Decimal("600000000"),
        zone=RegulationZone.SPECULATION_OVERHEATED,
        housing_status=HousingStatus.NO_HOUSE,
        is_capital_region=True,
        required_amount=Decimal("200000000"),
        months=360,
        as_of=_AS_OF,
    )


def _loan_result() -> LoanSimulationResult:
    return LoanSimulationResult(
        executable=(
            LoanComputation(
                product_name="KB 테스트 주택담보대출",
                option=_OPTION,
                status=EvaluationStatus.PASS,
                amount=Decimal("200000000"),
                annual_rate=Decimal("0.035"),
                dsr_annual_rate=Decimal("0.045"),
                months=360,
            ),
        ),
        policy_as_of=_AS_OF,
        policy_sources=("금융위원회 테스트 정책",),
        notes=("규제 기준일 2026-07-30",),
    )


def _savings_result() -> SavingsPortfolioResult:
    allocation = SavingsPortfolioAllocation(
        candidate_id="savings:1",
        product_id="1",
        product_name="KB 테스트 정기예금",
        institution_code="001",
        institution_name="국민은행",
        source_version="test-pack@2026-07",
        product_kind=SavingsProductKind.TERM_DEPOSIT,
        allocation_basis=PortfolioAllocationBasis.LUMP_SUM,
        allocation_amount=Decimal("10000000"),
        term_months=12,
        maturity_date=date(2027, 7, 30),
        product_score=Decimal("80"),
        expected_total_principal=Decimal("10000000"),
        expected_maturity_amount=Decimal("10300000"),
        expected_net_interest=Decimal("300000"),
    )
    return SavingsPortfolioResult(
        status=SavingsPortfolioStatus.COMPLETE,
        allocations=(allocation,),
        monthly_allocated=Decimal(0),
        monthly_unallocated=Decimal(0),
        lump_sum_allocated=Decimal("10000000"),
        lump_sum_unallocated=Decimal(0),
        coverage_ratio=Decimal(1),
        expected_total_principal=Decimal("10000000"),
        expected_maturity_amount=Decimal("10300000"),
        expected_net_interest=Decimal("300000"),
        weighted_product_score=Decimal("80"),
        expected_return_score=Decimal("0.8"),
        maturity_risk=Decimal("0.1"),
        concentration_risk=Decimal("0.1"),
        liquidity_shortfall=Decimal(0),
        objective_score=Decimal("0.76"),
    )


def _validation(
    status: EvaluationStatus = EvaluationStatus.PASS,
) -> SavingsPortfolioPolicyValidation:
    return SavingsPortfolioPolicyValidation(status=status, decisions=())


def test_service_combines_friend_loan_result_and_verified_savings_portfolio() -> None:
    result = recommend_from_results(
        as_of=_AS_OF,
        loan_request=_loan_request(),
        loan_result=_loan_result(),
        savings_result=_savings_result(),
        savings_validation=_validation(),
        loan_supplements={
            "KB 테스트 주택담보대출": LoanRecommendationSupplement(
                additional_financial_cost=Decimal("500000"),
                repayment_flexibility_score=Decimal("0.8"),
            )
        },
    )

    assert result.status is RecommendationStatus.COMPLETE
    assert result.loan.primary is not None
    assert result.loan.primary.product_name == "KB 테스트 주택담보대출"
    assert result.loan.primary.annual_rate == Decimal("0.035")
    assert result.loan.primary.assessment_annual_rate == Decimal("0.045")
    assert result.loan.primary.score_status is ScoreStatus.COMPLETE
    assert result.savings.allocations[0].source_version == "test-pack@2026-07"
    assert result.loan.policy_sources == ("금융위원회 테스트 정책",)


def test_missing_savings_policy_validation_blocks_the_allocations() -> None:
    result = recommend_from_results(
        as_of=_AS_OF,
        savings_result=_savings_result(),
    )

    assert result.status is RecommendationStatus.NEEDS_REVIEW
    assert result.savings.status is ComponentStatus.UNKNOWN
    assert result.savings.allocations == ()
    assert result.missing_inputs == ("savings_policy_validation",)


def test_missing_loan_supplements_make_a_provisional_not_fabricated_score() -> None:
    result = recommend_from_results(
        as_of=_AS_OF,
        loan_request=_loan_request(),
        loan_result=_loan_result(),
    )

    assert result.status is RecommendationStatus.NEEDS_REVIEW
    assert result.loan.primary is not None
    assert result.loan.primary.score_status is ScoreStatus.PROVISIONAL
    assert result.loan.primary.total_financial_cost is None
    assert set(result.missing_inputs) == {"total_cost", "repayment_flexibility"}


def test_service_rejects_mismatched_policy_dates() -> None:
    with pytest.raises(ValueError, match="기준일"):
        recommend_from_results(
            as_of=date(2026, 7, 29),
            loan_request=_loan_request(),
            loan_result=_loan_result(),
        )
