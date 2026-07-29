from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.loan_engine_adapter import (
    BorrowerFinancialState,
    PolicyLimits,
    adapt_handoff_for_loan_max,
    compute_loan_max,
    compute_loan_option,
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


# --- 검수된 한도표를 거치는 경로 -------------------------------------------------
# 위 테스트들은 한도표에 없는 가상 상품이라 정규식 파서만 탄다. 아래는 실제
# 상품명으로 curated/loan_limits.py를 거쳐 계산까지 도달하는지 확인한다.

CURATED_BASE = {
    "source_type": "manual_pdf",
    "fin_prdt_nm": "KB 신용대출",
    "loan_lmt": (
        "최대 3.5억원 이내 "
        "(재직기간 1년미만 시 최대 1억원 이내, 종합통장자동대출은 최대 1.5억원 이내)"
    ),
}
CURATED_OPTIONS = (
    {
        "fin_prdt_nm": "KB 신용대출",
        "rpay_type_nm": "분할상환방식",
        "lend_rate_type_nm": "변동금리",
        "lend_rate_min": 5.0,
        "lend_rate_max": 7.0,
        "lend_rate_avg": 6.0,
    },
)
CURATED_PACK = ProductRulePack(
    product_name="KB 신용대출",
    category=ProductCategory.CREDIT_LOAN,
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


def _route_curated(facts: dict[str, object]):
    return route_product_candidates(
        [
            ProductCandidate(
                product_name="KB 신용대출",
                base_data=CURATED_BASE,
                option_list=CURATED_OPTIONS,
            )
        ],
        user_facts=facts,
        as_of=AS_OF,
        registry=ProductRulePackRegistry((CURATED_PACK,)),
    )


def _adapt_curated(facts: dict[str, object]):
    return adapt_handoff_for_loan_max(
        _route_curated(facts).forwardable[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("300000000"),
        months=60,
    )[0]


def test_curated_table_resolves_a_limit_the_parser_cannot() -> None:
    # 파서는 이 문장에서 숫자를 고를 수 없지만, 재직기간과 대출형태를 알면
    # 한도가 3.5억으로 확정된다.
    adaptation = _adapt_curated(
        {"age": 32, "employment_months": 60, "is_overdraft_type": False}
    )

    assert adaptation.status is EvaluationStatus.PASS
    assert adaptation.inputs is not None
    assert adaptation.inputs.product_limit_amount == Decimal("350000000")
    assert adaptation.assumptions == ()
    assert compute_loan_max(adaptation) > 0


def test_missing_conditions_produce_a_conservative_limit_with_a_recorded_assumption() -> None:
    adaptation = _adapt_curated({"age": 32})

    assert adaptation.status is EvaluationStatus.PASS
    assert adaptation.inputs is not None
    # 조건을 모르면 가능한 한도 중 최저값(1억)을 쓴다 — 과소평가는 안전하다.
    assert adaptation.inputs.product_limit_amount == Decimal("100000000")
    assert adaptation.assumptions != ()


def test_conservative_limit_never_exceeds_the_fully_specified_one() -> None:
    known = _adapt_curated({"age": 32, "employment_months": 60, "is_overdraft_type": False})
    unknown = _adapt_curated({"age": 32})
    assert known.inputs is not None
    assert unknown.inputs is not None
    assert compute_loan_max(unknown) <= compute_loan_max(known)


def test_uncapped_product_is_bound_by_policy_limits_not_by_a_product_cap() -> None:
    # "담보조사가격 ... 대출가능금액 이내"는 상품 상한이 없다는 뜻이므로,
    # 상품 한도가 요청액과 같아져 LTV·DTI·DSR만 남는다.
    base = {
        "source_type": "manual_pdf",
        "fin_prdt_nm": "KB 주택담보대출",
        "loan_lmt": (
            "담보조사가격 및 소득금액, 담보물건지 지역 등에 따른 대출가능금액 이내 "
            "(통장자동대출 최고 3억원 이내)"
        ),
    }
    pack = ProductRulePack(
        product_name="KB 주택담보대출",
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
    routing = route_product_candidates(
        [
            ProductCandidate(
                product_name="KB 주택담보대출",
                base_data=base,
                option_list=CURATED_OPTIONS,
            )
        ],
        user_facts={"age": 32, "is_overdraft_type": False},
        as_of=AS_OF,
        registry=ProductRulePackRegistry((pack,)),
    )
    adaptation = adapt_handoff_for_loan_max(
        routing.forwardable[0],
        borrower=BORROWER,
        policy_limits=POLICY_LIMITS,
        required_amount=Decimal("300000000"),
        months=360,
    )[0]

    assert adaptation.status is EvaluationStatus.PASS
    assert adaptation.inputs is not None
    assert adaptation.inputs.product_limit_amount == Decimal("300000000")
    assert adaptation.assumptions == ()


# --- 상품 최소 실행금액 -----------------------------------------------------------
# Rule Pack은 **요청금액**이 최소금액 이상인지만 본다. 소득·DSR·현금흐름 때문에
# 계산 결과가 최소금액 아래로 내려가면 판정은 PASS인데 실행은 불가능하다.

EMERGENCY_BASE = {
    "source_type": "manual_pdf",
    "fin_prdt_nm": "KB 비상금대출",
    "loan_lmt": "최소 50만원 ~ 최대 300만원",
}
EMERGENCY_OPTIONS = (
    {
        "fin_prdt_nm": "KB 비상금대출",
        "rpay_type_nm": "만기일시상환방식",
        "lend_rate_type_nm": "변동금리",
        "lend_rate_min": 5.0,
        "lend_rate_max": 7.0,
        "lend_rate_avg": 6.0,
    },
)
EMERGENCY_PACK = ProductRulePack(
    product_name="KB 비상금대출",
    category=ProductCategory.CREDIT_LOAN,
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


def _adapt_emergency(policy_limits: PolicyLimits, required_amount: str = "3000000"):
    routing = route_product_candidates(
        [
            ProductCandidate(
                product_name="KB 비상금대출",
                base_data=EMERGENCY_BASE,
                option_list=EMERGENCY_OPTIONS,
            )
        ],
        user_facts={"age": 32},
        as_of=AS_OF,
        registry=ProductRulePackRegistry((EMERGENCY_PACK,)),
    )
    return adapt_handoff_for_loan_max(
        routing.forwardable[0],
        borrower=BORROWER,
        policy_limits=policy_limits,
        required_amount=Decimal(required_amount),
        months=12,
    )[0]


def test_minimum_amount_reaches_the_adaptation() -> None:
    adaptation = _adapt_emergency(POLICY_LIMITS)
    assert adaptation.product_minimum_amount == Decimal("500000")


def test_result_below_the_product_minimum_is_not_executable() -> None:
    # 요청금액을 30만원으로 조여 계산 결과를 최소금액(50만원) 아래로 만든다.
    # LTV로 조이면 안 된다 — 신용대출은 LTV 규제 대상이 아니라 무시된다.
    adaptation = _adapt_emergency(POLICY_LIMITS, required_amount="300000")
    computation = compute_loan_option(adaptation)

    assert computation.amount < Decimal("500000")
    assert computation.status is EvaluationStatus.FAIL
    assert not computation.is_executable
    assert "최소 실행금액" in computation.reasons[0]


def test_result_at_exactly_the_product_minimum_is_executable() -> None:
    # 탐색 결과를 특정 금액에 정확히 맞출 수는 없으므로, 계산된 금액을 그대로
    # 최소금액으로 놓아 경계(미만이 아니라 이하)를 직접 확인한다.
    adaptation = _adapt_emergency(
        PolicyLimits(
            ltv_limit_amount=Decimal("500000"),
            dti_limit_amount=Decimal("400000000"),
        )
    )
    computed = compute_loan_max(adaptation)
    at_boundary = replace(adaptation, product_minimum_amount=computed)

    computation = compute_loan_option(at_boundary)

    assert computation.amount == computed
    assert computation.status is EvaluationStatus.PASS
    assert computation.is_executable

    # 1원만 높여도 실행 불가가 되어야 경계가 제대로 잡힌 것이다.
    just_above = replace(adaptation, product_minimum_amount=computed + Decimal("1"))
    assert compute_loan_option(just_above).status is EvaluationStatus.FAIL


def test_product_without_a_minimum_is_always_executable() -> None:
    adaptation = _adapt_curated({"age": 32, "employment_months": 60, "is_overdraft_type": False})
    computation = compute_loan_option(adaptation)

    assert computation.product_minimum_amount is None
    assert computation.status is EvaluationStatus.PASS


def test_compute_loan_option_carries_conservative_assumptions_through() -> None:
    adaptation = _adapt_curated({"age": 32})
    computation = compute_loan_option(adaptation)

    assert computation.assumptions == adaptation.assumptions
    assert computation.assumptions != ()


class TestDtiUsesInterestOnly:
    """DTI 분자는 기타 대출을 이자만 세고, DSR은 원금까지 센다(KB 자료 계산식).

    두 값을 뭉치면 DTI가 틀린다. 이자만 따로 받고, 없으면 DSR용 값으로
    대체하되 그 방향이 과소평가(안전)임을 고정한다.
    """

    def test_interest_only_field_is_used_when_present(self) -> None:
        borrower = replace(BORROWER, existing_annual_interest=Decimal("2000000"))
        assert borrower.dti_other_annual_interest == Decimal("2000000")

    def test_falls_back_to_the_dsr_figure_when_absent(self) -> None:
        assert BORROWER.existing_annual_interest is None
        assert BORROWER.dti_other_annual_interest == BORROWER.existing_annual_debt_service

    def test_the_fallback_never_overstates_the_dti_allowance(self) -> None:
        # 원리금은 이자보다 크므로 더 많이 빼게 되고, DTI 한도는 낮아진다.
        with_interest = replace(BORROWER, existing_annual_interest=Decimal("2000000"))
        assert with_interest.dti_other_annual_interest < BORROWER.dti_other_annual_interest
