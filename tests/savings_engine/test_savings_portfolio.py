"""예·적금 포트폴리오 배분 제약의 회귀 테스트.

목적·기능:
    월 적금과 일시예금 예산 분리, 상품한도, 동일상품 옵션 중복, 최대 상품 수,
    예금자보호, 부분배분과 공식 목적함수 선택이 이후 변경에도 유지되는지 검증한다.
근거:
    공식 설계안 §12.1·§25 및 역할분담 문서 §9.2의 MVP 완료 조건을 테스트로
    고정한다.
"""

from datetime import date
from decimal import Decimal

from app.engines.savings.models import (
    InterestType,
    SavingsCalculationResult,
    SavingsEvaluationResult,
    SavingsEvaluationStatus,
    SavingsProductKind,
    SavingsScoreComponents,
)
from app.engines.savings.portfolio import build_savings_portfolio
from app.engines.savings.portfolio_models import (
    PortfolioAllocationBasis,
    SavingsPortfolioCandidate,
    SavingsPortfolioInput,
    SavingsPortfolioPolicy,
    SavingsPortfolioStatus,
)


def _candidate(
    candidate_id: str,
    *,
    product_id: str | None = None,
    institution_code: str = "KB",
    kind: SavingsProductKind = SavingsProductKind.INSTALLMENT_SAVINGS,
    score: str = "80",
    rate_score: str = "0.8",
    maturity_fit: str = "1",
    liquidity: str = "0.8",
    minimum: str = "100000",
    maximum: str | None = "1000000",
    original_allocation: str = "100000",
    eligible: bool = True,
    protected: bool = True,
    term_months: int = 12,
    annual_rate: str = "0.04",
) -> SavingsPortfolioCandidate:
    original = Decimal(original_allocation)
    total_principal = (
        original
        if kind is SavingsProductKind.TERM_DEPOSIT
        else original * Decimal(term_months)
    )
    # 이자는 기간에 비례한다. 기본값(12개월)에서는 연이율 그대로라 기존 픽스처의
    # 숫자가 바뀌지 않는다.
    net_interest = total_principal * Decimal(annual_rate) * Decimal(term_months) / 12
    maturity_amount = total_principal + net_interest
    product_name = f"상품-{candidate_id}"
    calculation = SavingsCalculationResult(
        product_name=product_name,
        product_kind=kind,
        term_months=term_months,
        interest_type=InterestType.SIMPLE,
        reserve_type_name=(
            None
            if kind is SavingsProductKind.TERM_DEPOSIT
            else "자유적립식"
        ),
        annual_base_rate=Decimal(annual_rate),
        annual_max_rate=Decimal(annual_rate),
        expected_annual_rate=Decimal(annual_rate),
        bonus_achievement_probability=Decimal(0),
        total_principal=total_principal,
        gross_interest=net_interest,
        tax_amount=Decimal(0),
        net_interest=net_interest,
        maturity_amount=maturity_amount,
        annualized_net_return_rate=Decimal(annual_rate),
        net_return_rate=net_interest / total_principal,
    )
    status = (
        SavingsEvaluationStatus.ELIGIBLE
        if eligible
        else SavingsEvaluationStatus.INELIGIBLE
    )
    evaluation = SavingsEvaluationResult(
        product_name=product_name,
        term_months=term_months,
        maturity_date=date(2027, 7, 28),
        projected_institution_deposit=maturity_amount,
        status=status,
        score=Decimal(score) if eligible else None,
        components=(
            SavingsScoreComponents(
                rate_score=Decimal(rate_score),
                maturity_fit_score=Decimal(maturity_fit),
                liquidity_score=Decimal(liquidity),
                safety_score=Decimal(1),
                bonus_achievement_score=Decimal(1),
            )
            if eligible
            else None
        ),
        reasons=() if eligible else ("상품 평가 필수조건 미충족",),
    )
    return SavingsPortfolioCandidate(
        candidate_id=candidate_id,
        product_id=product_id or candidate_id,
        institution_code=institution_code,
        institution_name=f"은행-{institution_code}",
        source_version=f"{candidate_id}@2026-07-28",
        calculation=calculation,
        evaluation=evaluation,
        minimum_allocation=Decimal(minimum),
        maximum_allocation=(
            Decimal(maximum) if maximum is not None else None
        ),
        is_deposit_protected=protected,
    )


def _policy(
    *,
    max_products: int = 3,
    maturity_weight: str = "0",
    concentration_weight: str = "0",
    liquidity_weight: str = "0",
) -> SavingsPortfolioPolicy:
    return SavingsPortfolioPolicy(
        max_products=max_products,
        maturity_risk_weight=Decimal(maturity_weight),
        concentration_risk_weight=Decimal(concentration_weight),
        liquidity_shortfall_weight=Decimal(liquidity_weight),
    )


def _input(
    *candidates: SavingsPortfolioCandidate,
    monthly_budget: str = "0",
    lump_sum_budget: str = "0",
    existing: dict[str, Decimal] | None = None,
    protection_limit: str = "100000000",
    policy: SavingsPortfolioPolicy | None = None,
) -> SavingsPortfolioInput:
    return SavingsPortfolioInput(
        candidates=candidates,
        monthly_savings_budget=Decimal(monthly_budget),
        lump_sum_budget=Decimal(lump_sum_budget),
        existing_institution_deposits=existing or {},
        deposit_protection_limit=Decimal(protection_limit),
        policy=policy or _policy(),
    )


def test_monthly_and_lump_sum_budgets_are_allocated_separately() -> None:
    savings = _candidate(
        "saving",
        maximum="600000",
        kind=SavingsProductKind.INSTALLMENT_SAVINGS,
    )
    deposit = _candidate(
        "deposit",
        minimum="1000000",
        maximum="10000000",
        original_allocation="1000000",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="OTHER",
    )

    result = build_savings_portfolio(
        _input(
            savings,
            deposit,
            monthly_budget="600000",
            lump_sum_budget="10000000",
            policy=_policy(max_products=2),
        )
    )

    assert result.status is SavingsPortfolioStatus.COMPLETE
    assert result.monthly_allocated == Decimal("600000")
    assert result.lump_sum_allocated == Decimal("10000000")
    allocation_by_basis = {
        allocation.allocation_basis: allocation
        for allocation in result.allocations
    }
    assert (
        allocation_by_basis[PortfolioAllocationBasis.MONTHLY].allocation_amount
        == Decimal("600000")
    )
    assert (
        allocation_by_basis[PortfolioAllocationBasis.LUMP_SUM].allocation_amount
        == Decimal("10000000")
    )
    # 월 납입액은 12개월 원금으로, 예금은 일시예치 원금 그대로 환산된다.
    assert result.expected_total_principal == Decimal("17200000")


def test_higher_value_candidate_is_filled_before_next_candidate() -> None:
    high = _candidate(
        "high",
        score="95",
        rate_score="1",
        maximum="600000",
        institution_code="A",
    )
    low = _candidate(
        "low",
        score="70",
        rate_score="0.6",
        maximum="600000",
        institution_code="B",
    )

    result = build_savings_portfolio(
        _input(high, low, monthly_budget="1000000", policy=_policy(max_products=2))
    )

    amounts = {
        allocation.candidate_id: allocation.allocation_amount
        for allocation in result.allocations
    }
    assert result.status is SavingsPortfolioStatus.COMPLETE
    assert amounts == {"high": Decimal("600000"), "low": Decimal("400000")}


def test_a_short_term_must_not_win_by_packing_more_principal_under_the_limit() -> None:
    """예금자보호 한도가 물릴 때 짧은 만기가 이기면 안 된다.

    상한 절단은 **만기금액** 기준이라, 한도가 물리면 어떤 조합이든 만기 합계가
    같은 한도에 도달한다. 남는 차이는 그 금액을 만드는 데 드는 원금뿐이고 만기가
    짧을수록 이자가 적어 원금이 더 든다. 소진율(원금)로 조합을 고르면 이자를 가장
    적게 주는 상품이 이긴다 — 실제 DB로 돌렸을 때 2년 뒤가 목표인 사용자에게
    1개월 정기예금이 뽑혔다.
    """
    short_term = _candidate(
        "short",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="KB",
        minimum="1000000",
        maximum=None,
        original_allocation="1000000",
        term_months=1,
    )
    long_term = _candidate(
        "long",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="KB",
        minimum="1000000",
        maximum=None,
        original_allocation="1000000",
        term_months=24,
    )

    result = build_savings_portfolio(
        _input(
            short_term,
            long_term,
            lump_sum_budget="150000000",
            protection_limit="100000000",
            policy=_policy(max_products=1),
        )
    )

    chosen = {allocation.candidate_id for allocation in result.allocations}
    assert chosen == {"long"}
    # 짧은 쪽이 원금은 더 많이 담는다. 그게 바로 지면 안 되는 이유다.
    assert result.lump_sum_allocated < Decimal("100000000")


def test_a_lower_rate_product_still_beats_leaving_the_budget_idle() -> None:
    """수익률 **평균**으로 조합을 고르면 안 된다.

    ``objective_score``는 원금 가중 평균이라, 수익률이 조금 낮은 상품을 더해 이자
    총액을 늘리면 오히려 내려간다. 그것을 순위 앞에 두면 "가장 좋은 하나만 담고
    나머지 예산은 놀린다"가 최적이 된다 — 실제 DB로 돌렸을 때 보호 한도 여유
    4,100만원을 남긴 채 예금을 한 건도 담지 않았다.

    예산이 전부 배분 가능하면 ``_is_complete``가 먼저 걸려 이 함정이 드러나지
    않는다. 그래서 배분 용량(2,000만+3,000만)을 예산(1억)보다 작게 두어 어떤
    조합도 완전할 수 없게 만든다.
    """
    best = _candidate(
        "best",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="A",
        score="100",
        rate_score="1",
        minimum="1000000",
        maximum="20000000",
        original_allocation="1000000",
        annual_rate="0.05",
    )
    worse = _candidate(
        "worse",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="B",
        score="60",
        rate_score="0.5",
        minimum="1000000",
        maximum="30000000",
        original_allocation="1000000",
        annual_rate="0.02",
    )

    result = build_savings_portfolio(
        _input(best, worse, lump_sum_budget="100000000", policy=_policy(max_products=2))
    )

    chosen = {allocation.candidate_id for allocation in result.allocations}
    assert chosen == {"best", "worse"}
    # 수익률이 낮아도 놀리는 것보다는 낫다: 담을 수 있는 5,000만원을 다 담는다.
    assert result.lump_sum_allocated == Decimal("50000000")


def test_deposit_protection_capacity_is_shared_by_institution() -> None:
    kb = _candidate(
        "kb",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="KB",
        score="100",
        rate_score="1",
        minimum="100000",
        maximum=None,
        original_allocation="1000000",
    )
    other = _candidate(
        "other",
        kind=SavingsProductKind.TERM_DEPOSIT,
        institution_code="OTHER",
        score="80",
        rate_score="0.8",
        minimum="100000",
        maximum="2000000",
        original_allocation="1000000",
    )

    result = build_savings_portfolio(
        _input(
            kb,
            other,
            lump_sum_budget="2000000",
            existing={"KB": Decimal("49000000")},
            protection_limit="50000000",
            policy=_policy(max_products=2),
        )
    )

    assert result.status is SavingsPortfolioStatus.COMPLETE
    kb_exposure = next(
        exposure
        for exposure in result.institution_exposures
        if exposure.institution_code == "KB"
    )
    assert kb_exposure.within_protection_limit is True
    assert kb_exposure.protected_amount_for_limit <= Decimal("50000000")
    kb_allocation = next(
        allocation
        for allocation in result.allocations
        if allocation.candidate_id == "kb"
    )
    assert kb_allocation.allocation_amount < Decimal("1000000")


def test_max_product_count_returns_partial_instead_of_breaking_limits() -> None:
    candidates = tuple(
        _candidate(
            f"p{index}",
            institution_code=f"B{index}",
            maximum="400000",
        )
        for index in range(3)
    )

    result = build_savings_portfolio(
        _input(
            *candidates,
            monthly_budget="1000000",
            policy=_policy(max_products=2),
        )
    )

    assert result.status is SavingsPortfolioStatus.PARTIAL
    assert len(result.allocations) == 2
    assert result.monthly_allocated == Decimal("800000")
    assert result.monthly_unallocated == Decimal("200000")
    assert result.coverage_ratio == Decimal("0.8")


def test_two_options_of_same_product_are_not_selected_together() -> None:
    option_a = _candidate(
        "same-12m",
        product_id="same-product",
        maximum="600000",
        score="95",
    )
    option_b = _candidate(
        "same-24m",
        product_id="same-product",
        maximum="600000",
        score="90",
    )
    alternative = _candidate(
        "alternative",
        product_id="alternative",
        institution_code="OTHER",
        maximum="500000",
        score="80",
    )

    result = build_savings_portfolio(
        _input(
            option_a,
            option_b,
            alternative,
            monthly_budget="1000000",
            policy=_policy(max_products=2),
        )
    )

    assert result.status is SavingsPortfolioStatus.COMPLETE
    assert len({allocation.product_id for allocation in result.allocations}) == 2
    assert "alternative" in {
        allocation.candidate_id for allocation in result.allocations
    }


def test_institution_concentration_penalty_prefers_diversified_pair() -> None:
    top = _candidate(
        "top",
        institution_code="A",
        minimum="500000",
        maximum="500000",
        rate_score="1",
        score="95",
    )
    same_bank = _candidate(
        "same-bank",
        institution_code="A",
        minimum="500000",
        maximum="500000",
        rate_score="0.8",
        score="80",
    )
    other_bank = _candidate(
        "other-bank",
        institution_code="B",
        minimum="500000",
        maximum="500000",
        rate_score="0.8",
        score="80",
    )

    result = build_savings_portfolio(
        _input(
            top,
            same_bank,
            other_bank,
            monthly_budget="1000000",
            policy=_policy(max_products=2, concentration_weight="0.5"),
        )
    )

    assert {
        allocation.candidate_id for allocation in result.allocations
    } == {"top", "other-bank"}
    assert result.concentration_risk == Decimal("0.5")


def test_ineligible_candidate_is_preserved_as_exclusion() -> None:
    rejected = _candidate("rejected", eligible=False)
    accepted = _candidate("accepted", institution_code="OTHER")

    result = build_savings_portfolio(
        _input(
            rejected,
            accepted,
            monthly_budget="500000",
            policy=_policy(max_products=1),
        )
    )

    assert result.status is SavingsPortfolioStatus.COMPLETE
    assert result.allocations[0].candidate_id == "accepted"
    assert result.exclusions[0].candidate_id == "rejected"
    assert "필수조건 미충족" in result.exclusions[0].reasons[0]


def test_minimum_above_budget_is_infeasible_not_zero_allocation() -> None:
    candidate = _candidate(
        "too-large",
        minimum="500000",
        maximum="1000000",
    )

    result = build_savings_portfolio(
        _input(
            candidate,
            monthly_budget="300000",
            policy=_policy(max_products=1),
        )
    )

    assert result.status is SavingsPortfolioStatus.INFEASIBLE
    assert result.allocations == ()
    assert result.monthly_unallocated == Decimal("300000")


def test_zero_budgets_need_no_products() -> None:
    result = build_savings_portfolio(_input())

    assert result.status is SavingsPortfolioStatus.NO_ALLOCATION_REQUIRED
    assert result.coverage_ratio == Decimal(1)
    assert result.allocations == ()
