"""대출 후보와 예·적금 포트폴리오를 하나의 종합추천으로 만드는 순수 엔진.

이 파일은 상품 자격을 다시 판정하거나 대출한도·예적금 만기금액을 다시 계산하지
않는다. 앞 엔진이 확정한 값을 넘겨받아 대출 후보의 비교지표를 계산하고, 검증된
예적금 배분안과 함께 추천 완성도·결측·행동 사유를 구성한다.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from app.engines.loan.formulas import dsr, pmt
from app.engines.recommendation.models import (
    CombinedRecommendationInput,
    CombinedRecommendationResult,
    ComponentStatus,
    DecisionStatus,
    LoanCandidateInput,
    LoanOptionRecommendation,
    LoanRecommendationInput,
    LoanRecommendationSummary,
    LoanScoreComponents,
    RecommendationPolicy,
    RecommendationStatus,
    SavingsPlanInput,
    SavingsPlanStatus,
    SavingsRecommendationSummary,
    ScoreStatus,
)


def _clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class _ComputedLoan:
    candidate: LoanCandidateInput
    recommendation: LoanOptionRecommendation


def _interest_stability_score(
    base_payment: Decimal,
    stress_payment: Decimal | None,
    policy: RecommendationPolicy,
) -> Decimal | None:
    """스트레스 상환액 증가율을 0~1 안정성 점수로 바꾼다(공식 설계안 §14.4)."""

    if stress_payment is None:
        return None
    if base_payment == 0:
        return Decimal(1)
    increase_ratio = max(stress_payment - base_payment, Decimal(0)) / base_payment
    if policy.maximum_payment_increase_ratio == 0:
        return Decimal(1) if increase_ratio == 0 else Decimal(0)
    return _clamp(Decimal(1) - increase_ratio / policy.maximum_payment_increase_ratio)


def _compute_loan_metrics(
    candidate: LoanCandidateInput,
    payload: LoanRecommendationInput,
    policy: RecommendationPolicy,
) -> _ComputedLoan:
    principal = min(payload.required_amount, candidate.maximum_amount)
    monthly_payment = pmt(principal, candidate.annual_rate, payload.months)
    assessment_rate = candidate.assessment_annual_rate
    stress_payment = (
        None if assessment_rate is None else pmt(principal, assessment_rate, payload.months)
    )
    expected_dsr = dsr(
        existing_annual_debt_service=payload.existing_annual_debt_service,
        new_annual_debt_service=monthly_payment * Decimal(12),
        annual_income=payload.annual_income,
    )
    post_purchase_surplus = (
        payload.post_purchase_monthly_income
        - payload.post_purchase_monthly_expense
        - payload.other_existing_monthly_debt_service
        - monthly_payment
    )
    stress_surplus = (
        None
        if stress_payment is None
        else (
            payload.post_purchase_monthly_income
            - payload.post_purchase_monthly_expense
            - payload.other_existing_monthly_debt_service
            - stress_payment
        )
    )

    repayment_capacity = _clamp(
        Decimal(1) - expected_dsr / payload.safe_dsr
    )
    crisis_resilience = (
        None
        if stress_surplus is None or payload.buffer_target == 0
        else _clamp(stress_surplus / payload.buffer_target)
    )
    interest_stability = _interest_stability_score(
        monthly_payment,
        stress_payment,
        policy,
    )
    total_interest = monthly_payment * payload.months - principal
    total_financial_cost = (
        None
        if candidate.additional_financial_cost is None
        else total_interest + candidate.additional_financial_cost
    )
    shortfall = max(payload.required_amount - candidate.maximum_amount, Decimal(0))
    covers_required = shortfall <= policy.loan_amount_tolerance

    reasons: list[str] = []
    if shortfall == 0:
        reasons.append("필요 대출금액을 계산된 안전한도 안에서 전액 충당할 수 있습니다.")
    elif covers_required:
        reasons.append(
            f"계산 허용오차 이내의 자금 차이 {shortfall:,.0f}원이 남아 "
            "실행 전 은행 확정한도를 확인해야 합니다."
        )
    else:
        reasons.append(f"필요 대출금액 대비 {shortfall:,.0f}원이 부족합니다.")
    reasons.extend(candidate.assumptions)

    recommendation = LoanOptionRecommendation(
        candidate_id=candidate.candidate_id,
        product_name=candidate.product_name,
        option_name=candidate.option_name,
        maximum_amount=candidate.maximum_amount,
        recommended_amount=principal,
        funding_shortfall=shortfall,
        covers_required_amount=covers_required,
        annual_rate=candidate.annual_rate,
        assessment_annual_rate=assessment_rate,
        monthly_payment=monthly_payment,
        stress_monthly_payment=stress_payment,
        total_interest=total_interest,
        total_financial_cost=total_financial_cost,
        expected_dsr=expected_dsr,
        post_purchase_monthly_surplus=post_purchase_surplus,
        stress_monthly_surplus=stress_surplus,
        score=None,
        score_status=ScoreStatus.UNAVAILABLE,
        score_completeness=Decimal(0),
        score_components=LoanScoreComponents(
            repayment_capacity=repayment_capacity,
            total_cost=None,
            crisis_resilience=crisis_resilience,
            interest_stability=interest_stability,
            repayment_flexibility=candidate.repayment_flexibility_score,
        ),
        assumptions=candidate.assumptions,
        reasons=tuple(reasons),
    )
    return _ComputedLoan(candidate=candidate, recommendation=recommendation)


def _cost_scores(
    computed: tuple[_ComputedLoan, ...],
    required_amount: Decimal,
) -> dict[str, Decimal]:
    """동일 금액을 전액 조달하는 후보끼리만 총비용을 정규화한다.

    공식 설계안 §14.2는 대출금액과 기간을 동일하게 맞추라고 명시한다. 한도가
    부족한 후보를 자기 최대금액으로 계산해 비용이 작다고 우대하면 비교 기준이
    달라지므로, 전액 후보가 아니거나 비용 항목이 하나라도 미확인이면 점수화하지
    않는다.
    """

    comparable = tuple(
        item
        for item in computed
        if item.candidate.maximum_amount >= required_amount
    )
    if not comparable or any(
        item.recommendation.total_financial_cost is None for item in comparable
    ):
        return {}

    costs = {
        item.candidate.candidate_id: item.recommendation.total_financial_cost
        for item in comparable
    }
    # 위 조건에서 None이 제거됐음을 타입 검사기 대신 명시적으로 보장한다.
    numeric_costs = {key: value for key, value in costs.items() if value is not None}
    minimum = min(numeric_costs.values())
    maximum = max(numeric_costs.values())
    if maximum == minimum:
        return {key: Decimal(1) for key in numeric_costs}
    return {
        key: Decimal(1) - (value - minimum) / (maximum - minimum)
        for key, value in numeric_costs.items()
    }


def _apply_score(
    item: _ComputedLoan,
    *,
    cost_score: Decimal | None,
    policy: RecommendationPolicy,
) -> _ComputedLoan:
    components = replace(item.recommendation.score_components, total_cost=cost_score)
    values = {
        "repayment_capacity": components.repayment_capacity,
        "total_cost": components.total_cost,
        "crisis_resilience": components.crisis_resilience,
        "interest_stability": components.interest_stability,
        "repayment_flexibility": components.repayment_flexibility,
    }
    known_weight = sum(
        (
            policy.weights[name]
            for name, value in values.items()
            if value is not None
        ),
        Decimal(0),
    )
    missing = tuple(name for name, value in values.items() if value is None)

    if known_weight == 0 or known_weight < policy.minimum_score_completeness:
        score = None
        score_status = ScoreStatus.UNAVAILABLE
    else:
        weighted_sum = sum(
            (
                policy.weights[name] * value
                for name, value in values.items()
                if value is not None
            ),
            Decimal(0),
        )
        # 결측을 0점으로 만들지 않고 확인된 가중치 안에서만 임시 점수를 환산한다.
        score = Decimal(100) * weighted_sum / known_weight
        score_status = (
            ScoreStatus.COMPLETE if known_weight == Decimal(1) else ScoreStatus.PROVISIONAL
        )

    reasons = list(item.recommendation.reasons)
    if score_status is ScoreStatus.PROVISIONAL:
        reasons.append(
            "일부 비교항목이 없어 확인된 항목만 재가중한 임시 점수입니다: "
            + ", ".join(missing)
        )
    elif score_status is ScoreStatus.UNAVAILABLE:
        reasons.append(
            "확인된 비교항목의 가중치가 부족해 점수를 만들지 않았습니다: "
            + ", ".join(missing)
        )

    return replace(
        item,
        recommendation=replace(
            item.recommendation,
            score=score,
            score_status=score_status,
            score_completeness=known_weight,
            score_components=components,
            missing_score_components=missing,
            reasons=tuple(reasons),
        ),
    )


def _loan_sort_key(item: LoanOptionRecommendation) -> tuple[object, ...]:
    score_status_rank = {
        ScoreStatus.COMPLETE: 2,
        ScoreStatus.PROVISIONAL: 1,
        ScoreStatus.UNAVAILABLE: 0,
    }
    return (
        1 if item.covers_required_amount else 0,
        score_status_rank[item.score_status],
        item.score if item.score is not None else Decimal(-1),
        item.score_completeness,
        item.maximum_amount,
        -item.monthly_payment,
        item.product_name,
        item.option_name,
        item.candidate_id,
    )


def recommend_loans(
    payload: LoanRecommendationInput | None,
    *,
    policy: RecommendationPolicy,
) -> LoanRecommendationSummary:
    """실행 가능한 대출 옵션을 동일 금액·기간으로 점수화하고 최대 N개를 반환한다."""

    if payload is None:
        return LoanRecommendationSummary(
            status=ComponentStatus.NOT_REQUESTED,
            required_amount=Decimal(0),
            maximum_recommendable_amount=Decimal(0),
            funding_shortfall=Decimal(0),
            primary=None,
            alternatives=(),
            unresolved_count=0,
            rejected_count=0,
        )
    if payload.required_amount == 0:
        return LoanRecommendationSummary(
            status=ComponentStatus.NOT_REQUIRED,
            required_amount=Decimal(0),
            maximum_recommendable_amount=Decimal(0),
            funding_shortfall=Decimal(0),
            primary=None,
            alternatives=(),
            unresolved_count=payload.unresolved_count,
            rejected_count=payload.rejected_count,
            missing_inputs=payload.missing_inputs,
            reasons=("추가 대출 필요금액이 0원이므로 대출상품을 추천하지 않습니다.",),
            policy_sources=payload.policy_sources,
        )

    computed = tuple(
        _compute_loan_metrics(candidate, payload, policy)
        for candidate in payload.candidates
    )
    cost_scores = _cost_scores(computed, payload.required_amount)
    scored = tuple(
        _apply_score(
            item,
            cost_score=cost_scores.get(item.candidate.candidate_id),
            policy=policy,
        )
        for item in computed
    )
    ranked = tuple(
        sorted(
            (item.recommendation for item in scored),
            key=_loan_sort_key,
            reverse=True,
        )
    )
    selected = ranked[: policy.max_loan_recommendations]
    primary = selected[0] if selected else None
    alternatives = selected[1:] if selected else ()
    maximum = max(
        (candidate.maximum_amount for candidate in payload.candidates),
        default=Decimal(0),
    )
    shortfall = max(payload.required_amount - maximum, Decimal(0))

    if primary is None:
        status = (
            ComponentStatus.UNKNOWN
            if payload.missing_inputs or payload.unresolved_count
            else ComponentStatus.INFEASIBLE
        )
    elif primary.funding_shortfall > 0:
        status = ComponentStatus.PARTIAL
    else:
        status = ComponentStatus.READY

    reasons = list(payload.notes)
    if status is ComponentStatus.UNKNOWN:
        reasons.append("입력이 부족한 대출 후보가 있어 추천을 확정하지 못했습니다.")
    elif status is ComponentStatus.INFEASIBLE:
        reasons.append("필수조건과 안전한도를 통과한 실행 가능한 대출 후보가 없습니다.")
    elif status is ComponentStatus.PARTIAL:
        reasons.append(
            f"가장 큰 안전한도를 사용해도 필요금액 대비 {shortfall:,.0f}원이 부족합니다."
        )
    else:
        reasons.append("필수조건과 안전한도를 통과한 대출 후보가 필요금액을 충당합니다.")

    return LoanRecommendationSummary(
        status=status,
        required_amount=payload.required_amount,
        maximum_recommendable_amount=maximum,
        funding_shortfall=shortfall,
        primary=primary,
        alternatives=alternatives,
        unresolved_count=payload.unresolved_count,
        rejected_count=payload.rejected_count,
        missing_inputs=_dedupe(payload.missing_inputs),
        reasons=_dedupe(reasons),
        policy_sources=_dedupe(payload.policy_sources),
    )


def recommend_savings(payload: SavingsPlanInput | None) -> SavingsRecommendationSummary:
    """최종 상품정책이 PASS인 포트폴리오만 종합추천 결과로 전달한다."""

    if payload is None:
        return SavingsRecommendationSummary(
            status=ComponentStatus.NOT_REQUESTED,
            plan_status=None,
            policy_status=None,
            allocations=(),
            coverage_ratio=Decimal(0),
            monthly_unallocated=Decimal(0),
            lump_sum_unallocated=Decimal(0),
            expected_maturity_amount=Decimal(0),
            expected_net_interest=Decimal(0),
        )

    allocations = payload.allocations
    reasons = list(payload.reasons)
    missing_inputs = list(payload.missing_inputs)

    if payload.policy_status is DecisionStatus.UNKNOWN:
        status = ComponentStatus.UNKNOWN
        allocations = ()
        reasons.append("최종 상품정책 검증을 확정하지 못해 배분안을 추천으로 전달하지 않습니다.")
    elif payload.policy_status is DecisionStatus.FAIL:
        status = ComponentStatus.INFEASIBLE
        allocations = ()
        reasons.append("최종 상품정책 재검증에 실패해 배분안을 추천에서 제외했습니다.")
    elif payload.status is SavingsPlanStatus.COMPLETE:
        status = ComponentStatus.READY
        reasons.append("예·적금 예산이 정책검증을 통과한 상품에 모두 배분됐습니다.")
    elif payload.status is SavingsPlanStatus.PARTIAL:
        status = ComponentStatus.PARTIAL
        reasons.append("일부 예·적금 예산이 상품 제약 때문에 배분되지 않았습니다.")
    elif payload.status is SavingsPlanStatus.NO_ALLOCATION_REQUIRED:
        status = ComponentStatus.NOT_REQUIRED
        reasons.append("배분할 예·적금 예산이 없어 상품 추천이 필요하지 않습니다.")
    else:
        status = ComponentStatus.INFEASIBLE
        allocations = ()
        reasons.append("예산과 상품 제약을 함께 만족하는 예·적금 포트폴리오가 없습니다.")

    return SavingsRecommendationSummary(
        status=status,
        plan_status=payload.status,
        policy_status=payload.policy_status,
        allocations=allocations,
        coverage_ratio=payload.coverage_ratio,
        monthly_unallocated=payload.monthly_unallocated,
        lump_sum_unallocated=payload.lump_sum_unallocated,
        expected_maturity_amount=payload.expected_maturity_amount,
        expected_net_interest=payload.expected_net_interest,
        missing_inputs=_dedupe(missing_inputs),
        reasons=_dedupe(reasons),
    )


def _combined_status(
    loan: LoanRecommendationSummary,
    savings: SavingsRecommendationSummary,
) -> RecommendationStatus:
    active = tuple(
        status
        for status in (loan.status, savings.status)
        if status not in (ComponentStatus.NOT_REQUESTED, ComponentStatus.NOT_REQUIRED)
    )
    if ComponentStatus.UNKNOWN in active:
        return RecommendationStatus.NEEDS_REVIEW
    if (
        loan.primary is not None
        and (
            loan.primary.score_status is not ScoreStatus.COMPLETE
            or bool(loan.primary.assumptions)
        )
    ):
        return RecommendationStatus.NEEDS_REVIEW
    if not active:
        return RecommendationStatus.COMPLETE
    if all(status is ComponentStatus.READY for status in active):
        return RecommendationStatus.COMPLETE
    if any(status in (ComponentStatus.READY, ComponentStatus.PARTIAL) for status in active):
        return RecommendationStatus.PARTIAL
    return RecommendationStatus.INFEASIBLE


def build_combined_recommendation(
    payload: CombinedRecommendationInput,
) -> CombinedRecommendationResult:
    """대출과 예·적금의 독립 상태를 보존한 종합추천을 만든다."""

    loan = recommend_loans(payload.loan, policy=payload.policy)
    savings = recommend_savings(payload.savings)
    status = _combined_status(loan, savings)
    score_missing = (
        ()
        if loan.primary is None or loan.primary.score_status is ScoreStatus.COMPLETE
        else loan.primary.missing_score_components
    )
    missing_inputs = _dedupe(
        (*loan.missing_inputs, *savings.missing_inputs, *score_missing)
    )

    reasons: list[str] = []
    if status is RecommendationStatus.COMPLETE:
        reasons.append("요청된 금융 구성요소가 모두 확정되어 종합추천을 만들었습니다.")
    elif status is RecommendationStatus.PARTIAL:
        reasons.append("사용 가능한 추천은 있으나 일부 목표 또는 예산을 충족하지 못했습니다.")
    elif status is RecommendationStatus.NEEDS_REVIEW:
        reasons.append("결측 또는 임시 점수 항목이 있어 확인 후 종합추천을 확정해야 합니다.")
    else:
        reasons.append("현재 입력과 필수조건으로 실행 가능한 종합추천을 만들 수 없습니다.")

    return CombinedRecommendationResult(
        status=status,
        as_of=payload.as_of,
        loan=loan,
        savings=savings,
        reasons=tuple(reasons),
        missing_inputs=missing_inputs,
        policy_note=payload.policy.policy_note,
        disclaimers=(
            "대출 가능액과 추천은 승인 또는 실제 적용금리를 보장하지 않습니다.",
            "추천 점수는 서비스 내부 비교 기준이며 법정·공식 적합성 점수가 아닙니다.",
            "AI 설명 계층은 이 결과의 금액·점수·상품 순위를 변경할 수 없습니다.",
        ),
    )
