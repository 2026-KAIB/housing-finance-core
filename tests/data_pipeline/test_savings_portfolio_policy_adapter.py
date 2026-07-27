"""포트폴리오 최종 금액의 상품정책 재검증 경계 테스트.

목적·기능:
    최초 PASS 금액과 최종 배분액이 달라질 때 Rule Pack을 다시 실행하여 범위 초과를
    FAIL로, 원본 handoff 누락을 UNKNOWN으로 보존하는지 확인한다.
근거:
    공식 설계안 §11.1의 가입·납입 필터와 §12.1의 상품별 납입한도 제약을
    포트폴리오 뒤에서도 유지해야 한다.
"""

from datetime import date
from decimal import Decimal

from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    revalidate_savings_portfolio_policy,
)
from app.engines.savings.models import SavingsProductKind
from app.engines.savings.portfolio_models import (
    PortfolioAllocationBasis,
    SavingsPortfolioAllocation,
    SavingsPortfolioResult,
    SavingsPortfolioStatus,
)
from app.rule_engine.product_packs.handoff import (
    ProductCandidate,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductCategory,
    ProductRulePack,
)
from app.rule_engine.product_packs.packs import KB_STAR_SAVINGS_3_PACK
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

PACK = ProductRulePack(
    product_name="검증 적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="test-policy-1",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    rules=(
        ComparisonRule(
            code="AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="만 19세 이상이어야 합니다.",
        ),
        ComparisonRule(
            code="PAYMENT_RANGE",
            field_name="monthly_payment_amount",
            operator=ComparisonOperator.BETWEEN,
            expected=(10_000, 300_000),
            failure_reason="월 납입액은 1만원 이상 30만원 이하여야 합니다.",
        ),
    ),
)
REGISTRY = ProductRulePackRegistry((PACK,))


def _handoff():
    routing = route_product_candidates(
        [ProductCandidate(product_name="검증 적금")],
        user_facts={"age": 30, "monthly_payment_amount": Decimal("100000")},
        as_of=date(2026, 7, 28),
        registry=REGISTRY,
    )
    return routing.forwardable[0]


def _portfolio(
    amount: str,
    *,
    product_name: str = "검증 적금",
) -> SavingsPortfolioResult:
    allocation_amount = Decimal(amount)
    allocation = SavingsPortfolioAllocation(
        candidate_id="candidate-1",
        product_id="product-1",
        product_name=product_name,
        institution_code="KB",
        institution_name="국민은행",
        source_version="검증 적금@test-policy-1",
        product_kind=SavingsProductKind.INSTALLMENT_SAVINGS,
        allocation_basis=PortfolioAllocationBasis.MONTHLY,
        allocation_amount=allocation_amount,
        term_months=12,
        maturity_date=date(2027, 7, 28),
        product_score=Decimal("80"),
        expected_total_principal=allocation_amount * Decimal(12),
        expected_maturity_amount=allocation_amount * Decimal("12.4"),
        expected_net_interest=allocation_amount * Decimal("0.4"),
    )
    return SavingsPortfolioResult(
        status=SavingsPortfolioStatus.COMPLETE,
        allocations=(allocation,),
        monthly_allocated=allocation_amount,
        monthly_unallocated=Decimal(0),
        lump_sum_allocated=Decimal(0),
        lump_sum_unallocated=Decimal(0),
        coverage_ratio=Decimal(1),
        expected_total_principal=allocation.expected_total_principal,
        expected_maturity_amount=allocation.expected_maturity_amount,
        expected_net_interest=allocation.expected_net_interest,
        weighted_product_score=Decimal("80"),
        expected_return_score=Decimal("0.8"),
        maturity_risk=Decimal(0),
        concentration_risk=Decimal(1),
        liquidity_shortfall=Decimal("0.2"),
        objective_score=Decimal("80"),
    )


def test_final_amount_inside_pack_range_passes() -> None:
    validation = revalidate_savings_portfolio_policy(
        _portfolio("250000"),
        handoffs_by_candidate_id={"candidate-1": _handoff()},
        registry=REGISTRY,
    )

    assert validation.status is EvaluationStatus.PASS
    assert validation.valid is True
    assert validation.decisions[0].pack_version == "test-policy-1"


def test_final_amount_outside_pack_range_fails() -> None:
    validation = revalidate_savings_portfolio_policy(
        _portfolio("500000"),
        handoffs_by_candidate_id={"candidate-1": _handoff()},
        registry=REGISTRY,
    )

    assert validation.status is EvaluationStatus.FAIL
    assert validation.valid is False
    assert "30만원 이하" in validation.reasons[0]


def test_missing_original_handoff_is_unknown_not_pass() -> None:
    validation = revalidate_savings_portfolio_policy(
        _portfolio("250000"),
        handoffs_by_candidate_id={},
        registry=REGISTRY,
    )

    assert validation.status is EvaluationStatus.UNKNOWN
    assert "원본 ProductEngineHandoff" in validation.reasons[0]


def test_real_kb_pack_rechecks_changed_portfolio_amount() -> None:
    real_registry = ProductRulePackRegistry((KB_STAR_SAVINGS_3_PACK,))
    routing = route_product_candidates(
        [ProductCandidate(product_name="KB 스타적금 III")],
        user_facts={
            "age": 30,
            "applicant_type": "individual",
            "monthly_payment_amount": Decimal("100000"),
        },
        as_of=date(2026, 7, 28),
        registry=real_registry,
    )
    assert routing.forwardable

    validation = revalidate_savings_portfolio_policy(
        _portfolio("400000", product_name="KB 스타적금 III"),
        handoffs_by_candidate_id={"candidate-1": routing.forwardable[0]},
        registry=real_registry,
    )

    assert validation.status is EvaluationStatus.FAIL
    assert "30만원 이하" in validation.reasons[0]
