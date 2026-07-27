from datetime import date
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.savings_engine_adapter import (
    SavingsCalculationPolicy,
    adapt_handoff_for_savings_calculation,
    compute_savings,
)
from app.engines.savings.models import ContributionTiming, SavingsProductKind
from app.rule_engine.product_packs.handoff import (
    ProductCandidate,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductCategory,
    ProductRulePack,
)
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule

AS_OF = date(2026, 7, 27)

DEPOSIT_PACK = ProductRulePack(
    product_name="테스트 정기예금",
    category=ProductCategory.TERM_DEPOSIT,
    version="test-1",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    rules=(
        ComparisonRule(
            code="MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="미성년자는 가입할 수 없습니다.",
        ),
    ),
)

SAVINGS_PACK = ProductRulePack(
    product_name="테스트 적금",
    category=ProductCategory.INSTALLMENT_SAVINGS,
    version="test-1",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    rules=(
        ComparisonRule(
            code="MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="미성년자는 가입할 수 없습니다.",
        ),
    ),
)

REGISTRY = ProductRulePackRegistry((DEPOSIT_PACK, SAVINGS_PACK))

DEPOSIT = ProductCandidate(
    product_name="테스트 정기예금",
    base_data={
        "fin_prdt_nm": "테스트 정기예금",
        "category_code": "deposit",
        "max_limit": Decimal("50000000"),
    },
    option_list=(
        {
            "fin_prdt_nm": "테스트 정기예금",
            "save_trm": 12,
            "rsrv_type": None,
            "rsrv_type_nm": None,
            "intr_rate_type": "S",
            "intr_rate_type_nm": "단리",
            "intr_rate": Decimal("3.0"),
            "intr_rate2": Decimal("5.0"),
        },
    ),
)

SAVINGS = ProductCandidate(
    product_name="테스트 적금",
    base_data={"fin_prdt_nm": "테스트 적금", "category_code": "saving"},
    option_list=(
        {
            "fin_prdt_nm": "테스트 적금",
            "save_trm": 24,
            "rsrv_type": "F",
            "rsrv_type_nm": "자유적립식",
            "intr_rate_type": "S",
            "intr_rate_type_nm": "단리",
            "intr_rate": Decimal("3.2"),
            "intr_rate2": Decimal("4.2"),
        },
    ),
)


def _handoff(candidate: ProductCandidate, facts: dict[str, object]):
    routing = route_product_candidates(
        [candidate],
        user_facts=facts,
        as_of=AS_OF,
        registry=REGISTRY,
    )
    return routing.all_results[0]


def test_deposit_handoff_becomes_typed_calculation_input() -> None:
    handoff = _handoff(
        DEPOSIT,
        {"age": 30, "deposit_amount": Decimal("10000000")},
    )
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(
            tax_rate=Decimal("0.154"),
            bonus_achievement_probability=Decimal("0.5"),
        ),
    )[0]

    assert adaptation.status is EvaluationStatus.PASS
    assert adaptation.inputs is not None
    assert adaptation.inputs.product_kind is SavingsProductKind.TERM_DEPOSIT
    assert adaptation.inputs.annual_base_rate == Decimal("0.03")
    assert adaptation.inputs.deposit_amount == Decimal("10000000")
    assert adaptation.inputs.monthly_payment_amount is None

    result = compute_savings(adaptation)
    assert result.expected_annual_rate == Decimal("0.040")
    assert result.maturity_amount > result.total_principal


def test_installment_requires_explicit_contribution_timing() -> None:
    handoff = _handoff(
        SAVINGS,
        {"age": 30, "monthly_payment_amount": Decimal("500000")},
    )
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(
            tax_rate=Decimal("0.154"),
            bonus_achievement_probability=Decimal("0.5"),
        ),
    )[0]

    assert adaptation.status is EvaluationStatus.UNKNOWN
    assert adaptation.missing_inputs == ("contribution_timing",)


def test_installment_input_cannot_leak_into_deposit_field() -> None:
    handoff = _handoff(
        SAVINGS,
        {"age": 30, "monthly_payment_amount": Decimal("500000")},
    )
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(
            tax_rate=Decimal("0.154"),
            bonus_achievement_probability=Decimal("0.5"),
            contribution_timing=ContributionTiming.BEGINNING,
        ),
    )[0]

    assert adaptation.status is EvaluationStatus.PASS
    assert adaptation.inputs is not None
    assert adaptation.inputs.deposit_amount is None
    assert adaptation.inputs.monthly_payment_amount == Decimal("500000")
    assert adaptation.inputs.contribution_timing is ContributionTiming.BEGINNING


def test_missing_bonus_probability_is_unknown_not_base_rate_guess() -> None:
    handoff = _handoff(
        DEPOSIT,
        {"age": 30, "deposit_amount": Decimal("10000000")},
    )
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(tax_rate=Decimal("0.154")),
    )[0]

    assert adaptation.status is EvaluationStatus.UNKNOWN
    assert adaptation.missing_inputs == ("bonus_achievement_probability",)
    with pytest.raises(ValueError, match="확정되지 않았습니다"):
        compute_savings(adaptation)


def test_failed_rule_pack_result_is_propagated_without_calculation() -> None:
    handoff = _handoff(
        DEPOSIT,
        {"age": 17, "deposit_amount": Decimal("10000000")},
    )
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(
            tax_rate=Decimal("0.154"),
            bonus_achievement_probability=Decimal("0.5"),
        ),
    )[0]

    assert adaptation.status is EvaluationStatus.FAIL
    assert adaptation.inputs is None
    assert "미성년자는 가입할 수 없습니다." in adaptation.reasons


def test_missing_user_amount_is_reported_with_the_right_product_field() -> None:
    handoff = _handoff(DEPOSIT, {"age": 30})
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(
            tax_rate=Decimal("0.154"),
            bonus_achievement_probability=Decimal("0.5"),
        ),
    )[0]

    assert adaptation.status is EvaluationStatus.UNKNOWN
    assert adaptation.missing_inputs == ("deposit_amount",)


def test_equal_base_and_max_rate_does_not_require_irrelevant_probability() -> None:
    candidate = ProductCandidate(
        product_name=DEPOSIT.product_name,
        base_data=DEPOSIT.base_data,
        option_list=(
            {
                **DEPOSIT.option_list[0],
                "intr_rate2": Decimal("3.0"),
            },
        ),
    )
    handoff = _handoff(
        candidate,
        {"age": 30, "deposit_amount": Decimal("10000000")},
    )
    adaptation = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(tax_rate=Decimal("0.154")),
    )[0]

    assert adaptation.status is EvaluationStatus.PASS
    assert adaptation.inputs is not None
    assert adaptation.inputs.bonus_achievement_probability == Decimal(0)


def test_nonstandard_extra_rate_mode_is_not_silently_dropped() -> None:
    candidate = ProductCandidate(
        product_name=DEPOSIT.product_name,
        base_data={
            **DEPOSIT.base_data,
            "extra_rate_info": {"cd_linked": {"description": "CD 연동형"}},
        },
        option_list=DEPOSIT.option_list,
    )
    handoff = _handoff(
        candidate,
        {"age": 30, "deposit_amount": Decimal("10000000")},
    )
    adaptations = adapt_handoff_for_savings_calculation(
        handoff,
        policy=SavingsCalculationPolicy(
            tax_rate=Decimal("0.154"),
            bonus_achievement_probability=Decimal("0.5"),
        ),
    )

    assert adaptations[0].status is EvaluationStatus.UNKNOWN
    assert adaptations[0].missing_inputs == ("extra_rate_info_calculation_policy",)
    assert adaptations[1].status is EvaluationStatus.PASS


def test_policy_rejects_invalid_ratios_at_the_boundary() -> None:
    with pytest.raises(ValueError, match="tax_rate"):
        SavingsCalculationPolicy(tax_rate=Decimal("1.5"))
