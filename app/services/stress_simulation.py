"""종합추천 결과와 차주 재무상태를 생활 스트레스 엔진에 연결한다.

이 서비스는 추천 결과를 다시 순위화하지 않는다. 선택된 추천대출 금액·실제 금리와
검증된 적금 월 납입액을 스트레스 입력으로 옮기고, 금리유형을 확인해 실제 상환액
충격 적용 여부를 결정한다.
"""

from decimal import Decimal

from app.engines.recommendation.models import (
    CombinedRecommendationResult,
    ComponentStatus,
)
from app.engines.savings.models import SavingsProductKind
from app.engines.stress.engine import run_stress_test
from app.engines.stress.models import (
    DEFAULT_STRESS_SCENARIOS,
    InterestRateShockApplicability,
    StressScenario,
    StressTestInput,
    StressTestResult,
)
from app.services.loan_simulation import LoanSimulationRequest


def resolve_interest_rate_shock_applicability(
    rate_type_name: str | None,
    *,
    loan_principal: Decimal,
) -> InterestRateShockApplicability:
    """정규화된 금리유형으로 생활 시나리오 금리 충격 적용 여부를 정한다.

    혼합형·주기형은 고정기간 정보가 있어야 어느 목표시점에 재산정되는지 알 수
    있으므로 UNKNOWN이다. 문자열에 "고정"이 들어간다는 이유만으로 전체 기간
    고정이라고 가정하지 않는다.
    """

    if loan_principal == 0:
        return InterestRateShockApplicability.NOT_APPLIES
    if rate_type_name is None:
        return InterestRateShockApplicability.UNKNOWN
    normalized = rate_type_name.strip().lower()
    if any(token in normalized for token in ("혼합", "주기", "재산정")):
        return InterestRateShockApplicability.UNKNOWN
    if "변동" in normalized:
        return InterestRateShockApplicability.APPLIES
    if "고정" in normalized:
        return InterestRateShockApplicability.NOT_APPLIES
    return InterestRateShockApplicability.UNKNOWN


def _monthly_savings_commitment(
    recommendation: CombinedRecommendationResult,
) -> Decimal | None:
    savings = recommendation.savings
    if savings.status is ComponentStatus.UNKNOWN:
        return None
    if savings.status in (
        ComponentStatus.NOT_REQUESTED,
        ComponentStatus.NOT_REQUIRED,
        ComponentStatus.INFEASIBLE,
    ):
        return Decimal(0)
    return sum(
        (
            allocation.allocation_amount
            for allocation in savings.allocations
            if allocation.product_kind == SavingsProductKind.INSTALLMENT_SAVINGS.value
        ),
        Decimal(0),
    )


def stress_recommendation(
    recommendation: CombinedRecommendationResult,
    *,
    loan_request: LoanSimulationRequest,
    scenarios: tuple[StressScenario, ...] = DEFAULT_STRESS_SCENARIOS,
) -> StressTestResult:
    """종합추천에서 선택된 계획을 금리·소득·생활비 시나리오로 검증한다."""

    if recommendation.as_of != loan_request.as_of:
        raise ValueError(
            "종합추천 기준일과 대출 요청 기준일이 다릅니다: "
            f"recommendation={recommendation.as_of}, request={loan_request.as_of}"
        )

    primary = recommendation.loan.primary
    precondition_missing: list[str] = []
    if primary is None:
        principal = Decimal(0)
        annual_rate = Decimal(0)
        rate_type_name = None
        if recommendation.loan.required_amount > 0:
            precondition_missing.append("recommended_loan_option")
    else:
        principal = primary.recommended_amount
        annual_rate = primary.annual_rate
        rate_type_name = primary.rate_type_name

    # **추천안이 실제로 갚는 기간으로 판정한다.** 요청 만기를 쓰면 월 상환액이
    # 실제보다 작게 나오고, 그만큼 스트레스가 느슨해진다 — 계산 계층이 만기를
    # 줄이기 시작한 뒤로 360개월과 34개월이 갈렸고, 그 차이가 6배가 넘었다.
    #
    # 추천할 대출이 없을 때만 요청 만기로 물러선다. 그때는 원금이 0이라 기간이
    # 판정에 영향을 주지 않으며, `StressTestInput`이 양수 기간을 요구한다.
    months = recommendation.loan.months
    if months is None:
        if primary is not None:
            raise ValueError(
                "추천된 대출이 있는데 상환 기간이 없습니다. "
                "요청 만기로 대체하면 월 상환액을 실제보다 작게 잡습니다."
            )
        months = loan_request.months

    borrower = loan_request.borrower
    monthly_savings = _monthly_savings_commitment(recommendation)
    scope_notes = [
        "금리 충격은 추천된 신규 대출에만 적용하며 기존 대출 상환액은 고정합니다.",
        "소득 감소는 연소득과 구매 후 월소득에 같은 비율로 적용합니다.",
        "생활비 증가는 구매 후 월지출과 필수생활비 Buffer 기준에 함께 적용합니다.",
    ]
    if monthly_savings is None:
        scope_notes.append("예·적금 정책검증이 미확정되어 월 적금 납입 지속성은 UNKNOWN입니다.")
    if primary is not None:
        scope_notes.append(
            f"스트레스 대상 추천대출: {primary.product_name} / {primary.option_name}"
        )
        # 어느 기간으로 판정했는지를 밝힌다. 요청 만기와 다를 수 있고, 다르면
        # 월 상환액이 문서의 다른 절과 달라 보이기 때문이다.
        scope_notes.append(f"상환 기간 {months}개월 기준으로 판정합니다.")

    return run_stress_test(
        StressTestInput(
            as_of=recommendation.as_of,
            loan_principal=principal,
            annual_rate=annual_rate,
            months=months,
            annual_income=borrower.annual_income,
            existing_annual_debt_service=borrower.existing_annual_debt_service,
            post_purchase_monthly_income=borrower.post_purchase_monthly_income,
            post_purchase_monthly_expense=borrower.post_purchase_monthly_expense,
            other_existing_monthly_debt_service=(
                borrower.other_existing_monthly_debt_service
            ),
            monthly_essential_expense=borrower.monthly_essential_expense,
            safe_dsr=borrower.safe_dsr,
            monthly_savings_commitment=monthly_savings,
            interest_rate_shock_applicability=(
                resolve_interest_rate_shock_applicability(
                    rate_type_name,
                    loan_principal=principal,
                )
            ),
            scenarios=scenarios,
            precondition_missing_inputs=tuple(precondition_missing),
            scope_notes=tuple(scope_notes),
        )
    )
