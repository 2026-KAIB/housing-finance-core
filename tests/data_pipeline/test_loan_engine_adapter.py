from datetime import date
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.loan_engine_adapter import (
    BorrowerFinancialState,
    PolicyLimits,
    adapt_handoff_for_loan_max,
    compute_loan_max,
)
from app.engines.loan.formulas import loan_max
from app.rule_engine.product_packs.handoff import ProductCandidate, route_product_candidates
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductCategory,
    ProductRulePack,
)
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

AS_OF = date(2026, 7, 27)

# 실제 원천 데이터(selected_23_products.json)에서 가져온 형태.
MORTGAGE_BASE = {
    "source_type": "manual_pdf",
    "fin_prdt_nm": "테스트 아파트담보대출",
    "loan_lmt": "최소 1천만원 이상 최대 10억원 이내",
}
MORTGAGE_OPTIONS = (
    {
        "fin_prdt_nm": "테스트 아파트담보대출",
        "mrtg_type_nm": "아파트/주택",
        "rpay_type_nm": "분할상환방식",
        "lend_rate_type_nm": "변동금리(금융채 5년)",
        "lend_rate_min": 4.0,
        "lend_rate_max": 5.0,
        "lend_rate_avg": 4.5,
    },
    {
        "fin_prdt_nm": "테스트 아파트담보대출",
        "mrtg_type_nm": "아파트/주택",
        "rpay_type_nm": "분할상환방식",
        "lend_rate_type_nm": "고정금리",
        "lend_rate_min": 5.0,
        "lend_rate_max": 6.0,
        "lend_rate_avg": 5.5,
    },
)

TEST_PACK = ProductRulePack(
    product_name="테스트 아파트담보대출",
    category=ProductCategory.MORTGAGE_LOAN,
    version="test-1",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    rules=(
        ComparisonRule(
            code="TEST_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="미성년자는 신청할 수 없습니다.",
        ),
    ),
)

BORROWER = BorrowerFinancialState(
    annual_income=Decimal("60000000"),
    existing_annual_debt_service=Decimal("6000000"),
    post_purchase_monthly_income=Decimal("5000000"),
    post_purchase_monthly_expense=Decimal("2000000"),
    other_existing_monthly_debt_service=Decimal("500000"),
    monthly_essential_expense=Decimal("2000000"),
    safe_dsr=Decimal("0.40"),
)

POLICY_LIMITS = PolicyLimits(
    ltv_limit_amount=Decimal("490000000"),
    dti_limit_amount=Decimal("400000000"),
)


def _registry() -> ProductRulePackRegistry:
    return ProductRulePackRegistry((TEST_PACK,))


def _route(facts: dict[str, object], base_data: dict[str, object] | None = None):
    candidate = ProductCandidate(
        product_name="테스트 아파트담보대출",
        base_data=base_data if base_data is not None else MORTGAGE_BASE,
        option_list=MORTGAGE_OPTIONS,
    )
    return route_product_candidates(
        [candidate],
        user_facts=facts,
        as_of=AS_OF,
        registry=_registry(),
    )


def test_passing_product_produces_one_input_set_per_option() -> None:
    routing = _route({"age": 32})
    assert len(routing.forwardable) == 1

    adaptations = adapt_handoff_for_loan_max(
        routing.forwardable[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("400000000"),
        months=360,
    )

    assert len(adaptations) == 2
    assert all(a.status is EvaluationStatus.PASS for a in adaptations)
    # 옵션마다 금리가 다르므로 입력도 옵션 수만큼 나온다(퍼센트→비율 변환 확인).
    assert adaptations[0].inputs is not None
    assert adaptations[0].inputs.annual_rate == Decimal("0.045")
    assert adaptations[1].inputs is not None
    assert adaptations[1].inputs.annual_rate == Decimal("0.055")


def test_adapted_inputs_drive_loan_max_end_to_end() -> None:
    routing = _route({"age": 32})
    adaptation = adapt_handoff_for_loan_max(
        routing.forwardable[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("400000000"),
        months=360,
    )[0]

    result = compute_loan_max(adaptation)

    # 어댑터를 거친 값이 loan_max()를 직접 호출한 것과 동일해야 한다.
    assert result == loan_max(
        ltv_limit_amount=Decimal("490000000"),
        product_limit_amount=Decimal("1000000000"),
        dti_limit_amount=Decimal("400000000"),
        required_amount=Decimal("400000000"),
        annual_rate=Decimal("0.045"),
        months=360,
        existing_annual_debt_service=Decimal("6000000"),
        annual_income=Decimal("60000000"),
        safe_dsr=Decimal("0.40"),
        post_purchase_monthly_income=Decimal("5000000"),
        post_purchase_monthly_expense=Decimal("2000000"),
        other_existing_monthly_debt_service=Decimal("500000"),
        buffer_target=Decimal("300000"),
    )
    assert result > 0


def test_buffer_target_follows_appendix_a8() -> None:
    # 필수생활비 400만원 → Buffer = max(30만, 40만) = 40만원.
    borrower = BorrowerFinancialState(
        annual_income=Decimal("60000000"),
        existing_annual_debt_service=Decimal("6000000"),
        post_purchase_monthly_income=Decimal("5000000"),
        post_purchase_monthly_expense=Decimal("2000000"),
        other_existing_monthly_debt_service=Decimal("500000"),
        monthly_essential_expense=Decimal("4000000"),
        safe_dsr=Decimal("0.40"),
    )

    assert borrower.buffer_target == Decimal("400000")
    # 필수생활비 200만원 → max(30만, 20만) = 30만원 하한이 걸린다.
    assert BORROWER.buffer_target == Decimal("300000")


def test_failed_product_is_not_adapted() -> None:
    routing = _route({"age": 17})
    assert len(routing.rejected) == 1

    adaptations = adapt_handoff_for_loan_max(
        routing.rejected[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("400000000"),
        months=360,
    )

    assert len(adaptations) == 1
    assert adaptations[0].status is EvaluationStatus.FAIL
    assert adaptations[0].inputs is None
    assert "미성년자는 신청할 수 없습니다." in adaptations[0].reasons


def test_unknown_eligibility_is_propagated_not_guessed() -> None:
    # age를 모르면 Rule Pack이 UNKNOWN을 낸다 — 어댑터가 PASS로 승격시키면 안 된다.
    routing = _route({})
    assert len(routing.needs_review) == 1

    adaptations = adapt_handoff_for_loan_max(
        routing.needs_review[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("400000000"),
        months=360,
    )

    assert adaptations[0].status is EvaluationStatus.UNKNOWN
    assert adaptations[0].inputs is None


def test_unparseable_product_limit_yields_unknown_not_a_guess() -> None:
    # 실제 KB 신용대출 형태의 조건부 한도 — 숫자로 확정할 수 없으면 UNKNOWN이다.
    base = dict(MORTGAGE_BASE)
    base["loan_lmt"] = "최대 3.5억원 이내 (재직기간 1년미만 시 최대 1억원 이내)"
    routing = _route({"age": 32}, base_data=base)

    adaptations = adapt_handoff_for_loan_max(
        routing.forwardable[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("400000000"),
        months=360,
    )

    assert all(a.status is EvaluationStatus.UNKNOWN for a in adaptations)
    assert adaptations[0].missing_inputs == ("product_limit_amount",)
    assert adaptations[0].inputs is None


def test_compute_loan_max_refuses_unknown_instead_of_returning_zero() -> None:
    base = dict(MORTGAGE_BASE)
    base["loan_lmt"] = "담보조사가격에 따름"
    routing = _route({"age": 32}, base_data=base)
    adaptation = adapt_handoff_for_loan_max(
        routing.forwardable[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("400000000"),
        months=360,
    )[0]

    # UNKNOWN을 0원으로 뭉개면 "한도 0"과 "한도 모름"이 구분되지 않는다.
    with pytest.raises(ValueError, match="확정되지 않았습니다"):
        compute_loan_max(adaptation)
