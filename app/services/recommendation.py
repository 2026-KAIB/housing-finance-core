"""대출·예적금 결과를 순수 종합추천 엔진에 연결하는 조립 서비스.

목적:
    ``engines/recommendation``이 서비스·Rule Pack·포트폴리오 검증 객체에
    의존하지 않게 경계를 유지한다.
기능:
    친구가 구현한 ``LoanSimulationResult``와 예·적금 ``SavingsPortfolioResult``,
    최종 상품정책 검증 결과를 종합추천 입력으로 변환하고 엔진을 호출한다.
근거:
    서비스 계층만 여러 하위 계층을 알고 조립한다는 ``app/services`` 규약과,
    정책 재검증 PASS 배분안만 추천에 전달한다는 savings README 규약을 따른다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    SavingsPortfolioPolicyValidation,
)
from app.engines.recommendation.engine import build_combined_recommendation
from app.engines.recommendation.models import (
    DEFAULT_RECOMMENDATION_POLICY,
    CombinedRecommendationInput,
    CombinedRecommendationResult,
    DecisionStatus,
    LoanCandidateInput,
    LoanRecommendationInput,
    RecommendationPolicy,
    SavingsAllocationInput,
    SavingsPlanInput,
    SavingsPlanStatus,
)
from app.engines.savings.portfolio_models import SavingsPortfolioResult
from app.rule_engine.product_packs.models import EvaluationStatus
from app.services.loan_simulation import LoanSimulationRequest, LoanSimulationResult


@dataclass(frozen=True)
class LoanRecommendationSupplement:
    """현재 상품 DB에 아직 구조화되지 않은 대출 비교항목.

    값을 모르면 객체를 만들거나 0으로 채우지 않는다. 그러면 추천 엔진이 해당
    점수를 결측으로 유지하고 결과를 PROVISIONAL로 표시한다.
    """

    additional_financial_cost: Decimal | None = None
    repayment_flexibility_score: Decimal | None = None

    def __post_init__(self) -> None:
        if self.additional_financial_cost is not None and self.additional_financial_cost < 0:
            raise ValueError("additional_financial_cost은(는) 음수일 수 없습니다.")
        if self.repayment_flexibility_score is not None and not (
            Decimal(0) <= self.repayment_flexibility_score <= Decimal(1)
        ):
            raise ValueError("repayment_flexibility_score은(는) 0 이상 1 이하이어야 합니다.")


def _option_name(computation) -> str:
    option = computation.option
    if option is None:
        return "옵션 정보 없음"
    parts = (
        option.mortgage_type_name,
        option.repayment_type_name,
        option.rate_type_name,
    )
    return " / ".join(part for part in parts if part) or "기본 옵션"


def _decision_status(status: EvaluationStatus) -> DecisionStatus:
    return DecisionStatus(status.value)


def _loan_input(
    request: LoanSimulationRequest,
    result: LoanSimulationResult,
    *,
    supplements: Mapping[str, LoanRecommendationSupplement],
) -> LoanRecommendationInput:
    if result.policy_as_of is not None and result.policy_as_of != request.as_of:
        raise ValueError(
            "대출 요청 기준일과 결과의 정책 기준일이 다릅니다: "
            f"request={request.as_of}, result={result.policy_as_of}"
        )

    candidates: list[LoanCandidateInput] = []
    missing_inputs = list(result.missing_inputs)
    for index, computation in enumerate(result.executable, start=1):
        annual_rate = computation.annual_rate
        if annual_rate is None and computation.option is not None:
            # 이전 버전에서 생성된 결과와의 호환 경로. 최신 계산은 사용 금리를
            # LoanComputation에 직접 보존하므로 다시 선택하지 않는다.
            annual_rate = computation.option.rate(request.rate_selection)
        if annual_rate is None:
            missing_inputs.append(f"{computation.product_name}.annual_rate")
            continue
        if computation.months is not None and computation.months != request.months:
            raise ValueError(
                f"{computation.product_name}: 계산 기간과 요청 기간이 다릅니다 "
                f"(calculation={computation.months}, request={request.months})."
            )
        supplement = supplements.get(computation.product_name)
        option_name = _option_name(computation)
        candidates.append(
            LoanCandidateInput(
                candidate_id=f"loan:{index}:{computation.product_name}:{option_name}",
                product_name=computation.product_name,
                option_name=option_name,
                maximum_amount=computation.amount,
                annual_rate=annual_rate,
                assessment_annual_rate=computation.dsr_annual_rate,
                additional_financial_cost=(
                    None if supplement is None else supplement.additional_financial_cost
                ),
                repayment_flexibility_score=(
                    None if supplement is None else supplement.repayment_flexibility_score
                ),
                assumptions=computation.assumptions,
            )
        )

    for unresolved in result.unresolved:
        missing_inputs.extend(unresolved.missing_inputs)

    borrower = request.borrower
    return LoanRecommendationInput(
        required_amount=request.required_amount,
        months=request.months,
        annual_income=borrower.annual_income,
        existing_annual_debt_service=borrower.existing_annual_debt_service,
        post_purchase_monthly_income=borrower.post_purchase_monthly_income,
        post_purchase_monthly_expense=borrower.post_purchase_monthly_expense,
        other_existing_monthly_debt_service=borrower.other_existing_monthly_debt_service,
        buffer_target=borrower.buffer_target,
        safe_dsr=borrower.safe_dsr,
        candidates=tuple(candidates),
        unresolved_count=len(result.unresolved),
        rejected_count=len(result.rejected) + len(result.not_executable),
        missing_inputs=tuple(dict.fromkeys(missing_inputs)),
        policy_sources=result.policy_sources,
        notes=result.notes,
    )


def _savings_input(
    result: SavingsPortfolioResult,
    validation: SavingsPortfolioPolicyValidation | None,
) -> SavingsPlanInput:
    missing_inputs: list[str] = []
    reasons = list(result.reasons)
    if validation is None:
        policy_status = DecisionStatus.UNKNOWN
        missing_inputs.append("savings_policy_validation")
        reasons.append("예·적금 최종 상품정책 재검증 결과가 제공되지 않았습니다.")
    else:
        policy_status = _decision_status(validation.status)
        reasons.extend(validation.reasons)

    allocations = tuple(
        SavingsAllocationInput(
            candidate_id=allocation.candidate_id,
            product_name=allocation.product_name,
            product_kind=allocation.product_kind.value,
            institution_name=allocation.institution_name,
            allocation_amount=allocation.allocation_amount,
            term_months=allocation.term_months,
            maturity_date=allocation.maturity_date,
            expected_maturity_amount=allocation.expected_maturity_amount,
            expected_net_interest=allocation.expected_net_interest,
            product_score=allocation.product_score,
            source_version=allocation.source_version,
        )
        for allocation in result.allocations
    )
    return SavingsPlanInput(
        status=SavingsPlanStatus(result.status.value),
        policy_status=policy_status,
        allocations=allocations,
        coverage_ratio=result.coverage_ratio,
        monthly_allocated=result.monthly_allocated,
        monthly_unallocated=result.monthly_unallocated,
        lump_sum_allocated=result.lump_sum_allocated,
        lump_sum_unallocated=result.lump_sum_unallocated,
        expected_total_principal=result.expected_total_principal,
        expected_maturity_amount=result.expected_maturity_amount,
        expected_net_interest=result.expected_net_interest,
        reasons=tuple(dict.fromkeys(reasons)),
        missing_inputs=tuple(missing_inputs),
    )


def recommend_from_results(
    *,
    as_of: date,
    loan_request: LoanSimulationRequest | None = None,
    loan_result: LoanSimulationResult | None = None,
    savings_result: SavingsPortfolioResult | None = None,
    savings_validation: SavingsPortfolioPolicyValidation | None = None,
    loan_supplements: Mapping[str, LoanRecommendationSupplement] | None = None,
    policy: RecommendationPolicy = DEFAULT_RECOMMENDATION_POLICY,
) -> CombinedRecommendationResult:
    """이미 계산된 대출·예적금 결과를 종합추천으로 조립한다.

    API·배치 실행기는 이 함수만 호출하면 된다. 대출 요청과 결과는 한 쌍이어야
    하고, 예·적금 검증이 없으면 배분안을 추천으로 승격하지 않고 UNKNOWN으로
    보존한다.
    """

    if (loan_request is None) != (loan_result is None):
        raise ValueError("loan_request와 loan_result는 함께 제공해야 합니다.")
    if loan_request is not None and loan_request.as_of != as_of:
        raise ValueError(
            f"종합추천 기준일과 대출 요청 기준일이 다릅니다: {as_of} != {loan_request.as_of}"
        )
    if savings_result is None and savings_validation is not None:
        raise ValueError("savings_validation을 사용하려면 savings_result가 필요합니다.")

    loan = (
        None
        if loan_request is None or loan_result is None
        else _loan_input(
            loan_request,
            loan_result,
            supplements=loan_supplements or {},
        )
    )
    savings = (
        None
        if savings_result is None
        else _savings_input(savings_result, savings_validation)
    )
    return build_combined_recommendation(
        CombinedRecommendationInput(
            as_of=as_of,
            loan=loan,
            savings=savings,
            policy=policy,
        )
    )
