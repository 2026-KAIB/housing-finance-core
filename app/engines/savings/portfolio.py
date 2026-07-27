"""평가된 예·적금 옵션을 실행 가능한 납입 포트폴리오로 배분한다.

목적:
    상품 점수만 나열하지 않고 사용자의 월 적립 가능액과 현재 목돈을 실제 상품별
    금액으로 나누어, 다음 종합추천·전략 엔진이 바로 사용할 수 있게 한다.
기능:
    최대 3개 상품 조합을 결정론적으로 탐색하고 상품 한도, 상품 중복, 예금자보호
    한도와 예산을 지키는 배분안 중 공식 목적함수가 가장 좋은 결과를 선택한다.
근거:
    공식 설계안 §12.1의 네 가지 필수 제약, §25의 기대수익-위험-유동성 목적함수,
    역할분담 문서 §9.2의 MVP 규칙 기반 최대 2~3개 선택 방식을 코드로 옮겼다.
    가중치는 공식 수치가 아니므로 ``SavingsPortfolioPolicy`` 입력으로만 받는다.

주의:
    이 모듈은 DB, Rule Pack, API를 호출하지 않는 순수 계산 계층이다. 후보의
    최소·최대 납입액과 정책 버전은 앞 계층이 검증해 전달해야 한다.
"""

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from app.engines.savings.models import SavingsEvaluationStatus, SavingsProductKind
from app.engines.savings.portfolio_models import (
    InstitutionExposure,
    PortfolioAllocationBasis,
    PortfolioCandidateExclusion,
    SavingsPortfolioAllocation,
    SavingsPortfolioCandidate,
    SavingsPortfolioInput,
    SavingsPortfolioResult,
    SavingsPortfolioStatus,
)


@dataclass(frozen=True)
class _PreparedCandidate:
    candidate: SavingsPortfolioCandidate
    original_allocation: Decimal
    principal_per_allocation: Decimal
    maturity_per_allocation: Decimal
    net_interest_per_allocation: Decimal


@dataclass(frozen=True)
class _PortfolioPlan:
    allocations: tuple[SavingsPortfolioAllocation, ...]
    monthly_allocated: Decimal
    lump_sum_allocated: Decimal
    coverage_ratio: Decimal
    weighted_product_score: Decimal
    expected_return_score: Decimal
    maturity_risk: Decimal
    concentration_risk: Decimal
    liquidity_shortfall: Decimal
    objective_score: Decimal
    institution_exposures: tuple[InstitutionExposure, ...]


def _prepare_candidate(candidate: SavingsPortfolioCandidate) -> _PreparedCandidate:
    calculation = candidate.calculation
    if calculation.product_kind is SavingsProductKind.TERM_DEPOSIT:
        original_allocation = calculation.total_principal
        principal_per_allocation = Decimal(1)
    else:
        original_allocation = calculation.total_principal / Decimal(
            calculation.term_months
        )
        principal_per_allocation = Decimal(calculation.term_months)

    return _PreparedCandidate(
        candidate=candidate,
        original_allocation=original_allocation,
        principal_per_allocation=principal_per_allocation,
        maturity_per_allocation=calculation.maturity_amount / original_allocation,
        net_interest_per_allocation=calculation.net_interest / original_allocation,
    )


def _filter_candidates(
    payload: SavingsPortfolioInput,
) -> tuple[tuple[_PreparedCandidate, ...], tuple[PortfolioCandidateExclusion, ...]]:
    prepared: list[_PreparedCandidate] = []
    exclusions: list[PortfolioCandidateExclusion] = []
    seen_candidate_ids: set[str] = set()

    for candidate in payload.candidates:
        if candidate.candidate_id in seen_candidate_ids:
            raise ValueError(f"candidate_id가 중복되었습니다: {candidate.candidate_id}")
        seen_candidate_ids.add(candidate.candidate_id)

        reasons: list[str] = []
        if candidate.evaluation.status is not SavingsEvaluationStatus.ELIGIBLE:
            reasons.extend(candidate.evaluation.reasons or ("상품 평가를 통과하지 못했습니다.",))
        if candidate.evaluation.score is None or candidate.evaluation.components is None:
            reasons.append("포트폴리오 목적함수에 필요한 상품점수 구성요소가 없습니다.")
        if (
            candidate.allocation_basis is PortfolioAllocationBasis.MONTHLY
            and payload.monthly_savings_budget <= 0
        ):
            reasons.append("적금에 배분할 월 적립 예산이 없습니다.")
        if (
            candidate.allocation_basis is PortfolioAllocationBasis.LUMP_SUM
            and payload.lump_sum_budget <= 0
        ):
            reasons.append("예금에 배분할 일시예치 예산이 없습니다.")

        if reasons:
            exclusions.append(
                PortfolioCandidateExclusion(
                    candidate_id=candidate.candidate_id,
                    reasons=tuple(reasons),
                )
            )
            continue
        prepared.append(_prepare_candidate(candidate))

    prepared.sort(
        key=lambda item: (
            -(item.candidate.evaluation.score or Decimal(0)),
            -item.candidate.calculation.annualized_net_return_rate,
            item.candidate.candidate_id,
        )
    )
    return tuple(prepared), tuple(exclusions)


def _budget_for_basis(
    payload: SavingsPortfolioInput,
    basis: PortfolioAllocationBasis,
) -> Decimal:
    if basis is PortfolioAllocationBasis.MONTHLY:
        return payload.monthly_savings_budget
    return payload.lump_sum_budget


def _coverage_ratio(
    payload: SavingsPortfolioInput,
    *,
    monthly_allocated: Decimal,
    lump_sum_allocated: Decimal,
) -> Decimal:
    # 월 예산과 일시금은 시간 단위가 달라 원화 합계 비율로 비교하지 않는다.
    # 활성화된 각 버킷의 충족률을 동일 가중 평균해 한 버킷이 다른 버킷을 가리는
    # 단위 오류를 막는다.
    ratios: list[Decimal] = []
    if payload.monthly_savings_budget > 0:
        ratios.append(monthly_allocated / payload.monthly_savings_budget)
    if payload.lump_sum_budget > 0:
        ratios.append(lump_sum_allocated / payload.lump_sum_budget)
    if not ratios:
        return Decimal(1)
    return sum(ratios, start=Decimal(0)) / Decimal(len(ratios))


def _institution_capacity(
    payload: SavingsPortfolioInput,
    item: _PreparedCandidate,
    protected_new_maturity: dict[str, Decimal],
) -> Decimal | None:
    if not item.candidate.is_deposit_protected:
        return None
    institution_code = item.candidate.institution_code
    existing = payload.existing_institution_deposits.get(
        institution_code,
        Decimal(0),
    )
    used = protected_new_maturity.get(institution_code, Decimal(0))
    remaining = payload.deposit_protection_limit - existing - used
    if remaining <= 0:
        return Decimal(0)
    return remaining / item.maturity_per_allocation


def _candidate_value(item: _PreparedCandidate, payload: SavingsPortfolioInput) -> Decimal:
    components = item.candidate.evaluation.components
    assert components is not None
    return (
        components.rate_score
        - payload.policy.maturity_risk_weight
        * (Decimal(1) - components.maturity_fit_score)
        - payload.policy.liquidity_shortfall_weight
        * (Decimal(1) - components.liquidity_score)
    )


def _allocate_subset(
    payload: SavingsPortfolioInput,
    subset: tuple[_PreparedCandidate, ...],
) -> _PortfolioPlan | None:
    allocations = {
        item.candidate.candidate_id: item.candidate.minimum_allocation
        for item in subset
    }

    for basis in PortfolioAllocationBasis:
        minimum_total = sum(
            (
                allocations[item.candidate.candidate_id]
                for item in subset
                if item.candidate.allocation_basis is basis
            ),
            start=Decimal(0),
        )
        if minimum_total > _budget_for_basis(payload, basis):
            return None

    protected_new_maturity: dict[str, Decimal] = {}
    for item in subset:
        if not item.candidate.is_deposit_protected:
            continue
        amount = allocations[item.candidate.candidate_id]
        institution_code = item.candidate.institution_code
        protected_new_maturity[institution_code] = protected_new_maturity.get(
            institution_code,
            Decimal(0),
        ) + amount * item.maturity_per_allocation

    for institution_code, new_maturity in protected_new_maturity.items():
        existing = payload.existing_institution_deposits.get(
            institution_code,
            Decimal(0),
        )
        if existing + new_maturity > payload.deposit_protection_limit:
            return None

    remaining_by_basis = {
        basis: _budget_for_basis(payload, basis)
        - sum(
            (
                allocations[item.candidate.candidate_id]
                for item in subset
                if item.candidate.allocation_basis is basis
            ),
            start=Decimal(0),
        )
        for basis in PortfolioAllocationBasis
    }

    # MVP 규칙 기반 배분: 각 후보의 개별 기대가치가 높은 순서로 남은 예산을 채운다.
    # 기관집중도는 조합 선택의 목적함수에서 패널티로 반영한다(공식 설계 §25.3).
    ranked = sorted(
        subset,
        key=lambda item: (
            -_candidate_value(item, payload),
            -(item.candidate.evaluation.score or Decimal(0)),
            item.candidate.candidate_id,
        ),
    )
    for item in ranked:
        candidate = item.candidate
        basis = candidate.allocation_basis
        remaining_budget = remaining_by_basis[basis]
        if remaining_budget <= 0:
            continue

        current = allocations[candidate.candidate_id]
        product_capacity = (
            remaining_budget
            if candidate.maximum_allocation is None
            else max(Decimal(0), candidate.maximum_allocation - current)
        )
        protection_capacity = _institution_capacity(
            payload,
            item,
            protected_new_maturity,
        )
        increment = min(remaining_budget, product_capacity)
        if protection_capacity is not None:
            increment = min(increment, protection_capacity)
        if increment <= 0:
            continue

        allocations[candidate.candidate_id] += increment
        remaining_by_basis[basis] -= increment
        if candidate.is_deposit_protected:
            institution_code = candidate.institution_code
            protected_new_maturity[institution_code] = protected_new_maturity.get(
                institution_code,
                Decimal(0),
            ) + increment * item.maturity_per_allocation

    output_allocations = tuple(
        _to_output_allocation(item, allocations[item.candidate.candidate_id])
        for item in subset
    )
    monthly_allocated = sum(
        (
            allocation.allocation_amount
            for allocation in output_allocations
            if allocation.allocation_basis is PortfolioAllocationBasis.MONTHLY
        ),
        start=Decimal(0),
    )
    lump_sum_allocated = sum(
        (
            allocation.allocation_amount
            for allocation in output_allocations
            if allocation.allocation_basis is PortfolioAllocationBasis.LUMP_SUM
        ),
        start=Decimal(0),
    )
    metrics = _portfolio_metrics(payload, subset, output_allocations)

    return _PortfolioPlan(
        allocations=tuple(
            sorted(output_allocations, key=lambda allocation: allocation.candidate_id)
        ),
        monthly_allocated=monthly_allocated,
        lump_sum_allocated=lump_sum_allocated,
        coverage_ratio=_coverage_ratio(
            payload,
            monthly_allocated=monthly_allocated,
            lump_sum_allocated=lump_sum_allocated,
        ),
        weighted_product_score=metrics["weighted_product_score"],
        expected_return_score=metrics["expected_return_score"],
        maturity_risk=metrics["maturity_risk"],
        concentration_risk=metrics["concentration_risk"],
        liquidity_shortfall=metrics["liquidity_shortfall"],
        objective_score=metrics["objective_score"],
        institution_exposures=_institution_exposures(payload, subset, output_allocations),
    )


def _to_output_allocation(
    item: _PreparedCandidate,
    allocation_amount: Decimal,
) -> SavingsPortfolioAllocation:
    candidate = item.candidate
    evaluation_score = candidate.evaluation.score
    assert evaluation_score is not None
    return SavingsPortfolioAllocation(
        candidate_id=candidate.candidate_id,
        product_id=candidate.product_id,
        product_name=candidate.calculation.product_name,
        institution_code=candidate.institution_code,
        institution_name=candidate.institution_name,
        source_version=candidate.source_version,
        product_kind=candidate.calculation.product_kind,
        allocation_basis=candidate.allocation_basis,
        allocation_amount=allocation_amount,
        term_months=candidate.calculation.term_months,
        maturity_date=candidate.evaluation.maturity_date,
        product_score=evaluation_score,
        expected_total_principal=allocation_amount * item.principal_per_allocation,
        expected_maturity_amount=allocation_amount * item.maturity_per_allocation,
        expected_net_interest=allocation_amount * item.net_interest_per_allocation,
    )


def _weighted_average(
    values: tuple[tuple[Decimal, Decimal], ...],
) -> Decimal:
    total_weight = sum((weight for _, weight in values), start=Decimal(0))
    if total_weight <= 0:
        return Decimal(0)
    return sum(
        (value * weight for value, weight in values),
        start=Decimal(0),
    ) / total_weight


def _portfolio_metrics(
    payload: SavingsPortfolioInput,
    subset: tuple[_PreparedCandidate, ...],
    allocations: tuple[SavingsPortfolioAllocation, ...],
) -> dict[str, Decimal]:
    by_id = {item.candidate.candidate_id: item for item in subset}
    # 월 납입액과 일시예치금을 그대로 가중치로 섞지 않고, 각 상품 만기까지 실제로
    # 투입될 총 원금으로 환산한 뒤 지표를 가중 평균한다.
    weighted_product_score = _weighted_average(
        tuple(
            (allocation.product_score, allocation.expected_total_principal)
            for allocation in allocations
        )
    )
    expected_return_score = _weighted_average(
        tuple(
            (
                by_id[allocation.candidate_id].candidate.evaluation.components.rate_score,
                allocation.expected_total_principal,
            )
            for allocation in allocations
            if by_id[allocation.candidate_id].candidate.evaluation.components is not None
        )
    )
    maturity_fit = _weighted_average(
        tuple(
            (
                by_id[
                    allocation.candidate_id
                ].candidate.evaluation.components.maturity_fit_score,
                allocation.expected_total_principal,
            )
            for allocation in allocations
            if by_id[allocation.candidate_id].candidate.evaluation.components is not None
        )
    )
    liquidity = _weighted_average(
        tuple(
            (
                by_id[
                    allocation.candidate_id
                ].candidate.evaluation.components.liquidity_score,
                allocation.expected_total_principal,
            )
            for allocation in allocations
            if by_id[allocation.candidate_id].candidate.evaluation.components is not None
        )
    )
    maturity_risk = Decimal(1) - maturity_fit
    liquidity_shortfall = Decimal(1) - liquidity
    concentration_risk = _concentration_risk(payload, allocations)
    objective_score = Decimal(100) * (
        expected_return_score
        - payload.policy.maturity_risk_weight * maturity_risk
        - payload.policy.concentration_risk_weight * concentration_risk
        - payload.policy.liquidity_shortfall_weight * liquidity_shortfall
    )
    return {
        "weighted_product_score": weighted_product_score,
        "expected_return_score": expected_return_score,
        "maturity_risk": maturity_risk,
        "concentration_risk": concentration_risk,
        "liquidity_shortfall": liquidity_shortfall,
        "objective_score": objective_score,
    }


def _concentration_risk(
    payload: SavingsPortfolioInput,
    allocations: tuple[SavingsPortfolioAllocation, ...],
) -> Decimal:
    exposure = dict(payload.existing_institution_deposits)
    for allocation in allocations:
        exposure[allocation.institution_code] = exposure.get(
            allocation.institution_code,
            Decimal(0),
        ) + allocation.expected_maturity_amount
    total = sum(exposure.values(), start=Decimal(0))
    if total <= 0:
        return Decimal(0)
    # HHI(Σ 기관별 비중²)는 0~1이며 한 기관에 집중될수록 1에 가까워진다.
    return sum(
        ((amount / total) ** 2 for amount in exposure.values()),
        start=Decimal(0),
    )


def _institution_exposures(
    payload: SavingsPortfolioInput,
    subset: tuple[_PreparedCandidate, ...],
    allocations: tuple[SavingsPortfolioAllocation, ...],
) -> tuple[InstitutionExposure, ...]:
    candidate_by_id = {item.candidate.candidate_id: item.candidate for item in subset}
    new_maturity: dict[str, Decimal] = {}
    protected_new: dict[str, Decimal] = {}
    for allocation in allocations:
        code = allocation.institution_code
        new_maturity[code] = new_maturity.get(code, Decimal(0)) + (
            allocation.expected_maturity_amount
        )
        if candidate_by_id[allocation.candidate_id].is_deposit_protected:
            protected_new[code] = protected_new.get(code, Decimal(0)) + (
                allocation.expected_maturity_amount
            )

    institution_codes = (
        set(payload.existing_institution_deposits) | set(new_maturity) | set(protected_new)
    )
    exposures: list[InstitutionExposure] = []
    for code in sorted(institution_codes):
        existing = payload.existing_institution_deposits.get(code, Decimal(0))
        new_amount = new_maturity.get(code, Decimal(0))
        protected_amount = protected_new.get(code, Decimal(0))
        protected_for_limit = existing + protected_amount
        exposures.append(
            InstitutionExposure(
                institution_code=code,
                existing_deposit=existing,
                new_maturity_amount=new_amount,
                protected_new_maturity_amount=protected_amount,
                projected_total_exposure=existing + new_amount,
                protected_amount_for_limit=protected_for_limit,
                deposit_protection_limit=payload.deposit_protection_limit,
                within_protection_limit=(
                    protected_for_limit <= payload.deposit_protection_limit
                ),
            )
        )
    return tuple(exposures)


def _is_complete(payload: SavingsPortfolioInput, plan: _PortfolioPlan) -> bool:
    return (
        payload.monthly_savings_budget - plan.monthly_allocated
        <= payload.policy.allocation_tolerance
        and payload.lump_sum_budget - plan.lump_sum_allocated
        <= payload.policy.allocation_tolerance
    )


def _plan_is_better(
    payload: SavingsPortfolioInput,
    candidate: _PortfolioPlan,
    current: _PortfolioPlan | None,
) -> bool:
    if current is None:
        return True
    candidate_key = (
        int(_is_complete(payload, candidate)),
        candidate.coverage_ratio,
        candidate.objective_score,
        candidate.weighted_product_score,
        -len(candidate.allocations),
    )
    current_key = (
        int(_is_complete(payload, current)),
        current.coverage_ratio,
        current.objective_score,
        current.weighted_product_score,
        -len(current.allocations),
    )
    if candidate_key != current_key:
        return candidate_key > current_key
    candidate_ids = tuple(allocation.candidate_id for allocation in candidate.allocations)
    current_ids = tuple(allocation.candidate_id for allocation in current.allocations)
    return candidate_ids < current_ids


def build_savings_portfolio(
    payload: SavingsPortfolioInput,
) -> SavingsPortfolioResult:
    """필수 제약을 지키는 최대 3개 예·적금 배분안 중 목적함수 최댓값을 반환한다."""

    if payload.monthly_savings_budget == 0 and payload.lump_sum_budget == 0:
        return SavingsPortfolioResult(
            status=SavingsPortfolioStatus.NO_ALLOCATION_REQUIRED,
            allocations=(),
            monthly_allocated=Decimal(0),
            monthly_unallocated=Decimal(0),
            lump_sum_allocated=Decimal(0),
            lump_sum_unallocated=Decimal(0),
            coverage_ratio=Decimal(1),
            expected_total_principal=Decimal(0),
            expected_maturity_amount=Decimal(0),
            expected_net_interest=Decimal(0),
            weighted_product_score=None,
            expected_return_score=None,
            maturity_risk=None,
            concentration_risk=None,
            liquidity_shortfall=None,
            objective_score=None,
            reasons=("배분할 월 적립액과 일시예치금이 모두 0원입니다.",),
        )

    candidates, exclusions = _filter_candidates(payload)
    best: _PortfolioPlan | None = None
    max_products = min(payload.policy.max_products, len(candidates))
    for product_count in range(1, max_products + 1):
        for subset in combinations(candidates, product_count):
            # 한 상품의 기간·금리 옵션을 동시에 여러 계좌처럼 선택하지 않는다.
            product_ids = {item.candidate.product_id for item in subset}
            if len(product_ids) != len(subset):
                continue
            plan = _allocate_subset(payload, subset)
            if plan is not None and _plan_is_better(payload, plan, best):
                best = plan

    if best is None:
        return SavingsPortfolioResult(
            status=SavingsPortfolioStatus.INFEASIBLE,
            allocations=(),
            monthly_allocated=Decimal(0),
            monthly_unallocated=payload.monthly_savings_budget,
            lump_sum_allocated=Decimal(0),
            lump_sum_unallocated=payload.lump_sum_budget,
            coverage_ratio=Decimal(0),
            expected_total_principal=Decimal(0),
            expected_maturity_amount=Decimal(0),
            expected_net_interest=Decimal(0),
            weighted_product_score=None,
            expected_return_score=None,
            maturity_risk=None,
            concentration_risk=None,
            liquidity_shortfall=None,
            objective_score=None,
            exclusions=exclusions,
            reasons=(
                "상품 최소 납입액, 예산 또는 예금자보호 제약을 만족하는 조합이 없습니다.",
            ),
        )

    selected_ids = {allocation.candidate_id for allocation in best.allocations}
    all_valid_ids = {item.candidate.candidate_id for item in candidates}
    monthly_unallocated = max(
        Decimal(0),
        payload.monthly_savings_budget - best.monthly_allocated,
    )
    lump_sum_unallocated = max(
        Decimal(0),
        payload.lump_sum_budget - best.lump_sum_allocated,
    )
    status = (
        SavingsPortfolioStatus.COMPLETE
        if _is_complete(payload, best)
        else SavingsPortfolioStatus.PARTIAL
    )
    reasons: list[str] = []
    if status is SavingsPortfolioStatus.PARTIAL:
        if monthly_unallocated > payload.policy.allocation_tolerance:
            reasons.append(f"월 적립 예산 중 {monthly_unallocated}원이 배분되지 않았습니다.")
        if lump_sum_unallocated > payload.policy.allocation_tolerance:
            reasons.append(f"일시예치 예산 중 {lump_sum_unallocated}원이 배분되지 않았습니다.")

    return SavingsPortfolioResult(
        status=status,
        allocations=best.allocations,
        monthly_allocated=best.monthly_allocated,
        monthly_unallocated=monthly_unallocated,
        lump_sum_allocated=best.lump_sum_allocated,
        lump_sum_unallocated=lump_sum_unallocated,
        coverage_ratio=best.coverage_ratio,
        expected_total_principal=sum(
            (
                allocation.expected_total_principal
                for allocation in best.allocations
            ),
            start=Decimal(0),
        ),
        expected_maturity_amount=sum(
            (
                allocation.expected_maturity_amount
                for allocation in best.allocations
            ),
            start=Decimal(0),
        ),
        expected_net_interest=sum(
            (
                allocation.expected_net_interest
                for allocation in best.allocations
            ),
            start=Decimal(0),
        ),
        weighted_product_score=best.weighted_product_score,
        expected_return_score=best.expected_return_score,
        maturity_risk=best.maturity_risk,
        concentration_risk=best.concentration_risk,
        liquidity_shortfall=best.liquidity_shortfall,
        objective_score=best.objective_score,
        institution_exposures=best.institution_exposures,
        unselected_candidate_ids=tuple(sorted(all_valid_ids - selected_ids)),
        exclusions=exclusions,
        reasons=tuple(reasons),
    )
