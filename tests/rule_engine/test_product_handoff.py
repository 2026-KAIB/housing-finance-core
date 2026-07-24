from datetime import date

from app.rule_engine.product_packs import (
    EvaluationStatus,
    ProductCandidate,
    ProductRulePackRegistry,
    route_product_candidates,
)
from app.rule_engine.product_packs.packs.kb_star_term_deposit import (
    KB_STAR_TERM_DEPOSIT_PACK,
)
from app.rule_engine.product_packs.packs.kb_super_term_deposit import (
    KB_SUPER_TERM_DEPOSIT_PACK,
)

REGISTRY = ProductRulePackRegistry(
    (KB_STAR_TERM_DEPOSIT_PACK, KB_SUPER_TERM_DEPOSIT_PACK)
)
AS_OF = date(2026, 7, 24)
STAR_OPTIONS = (
    {"save_trm": "1", "intr_rate": 2.05, "intr_rate2": 2.55},
    {"save_trm": "12", "intr_rate": 2.40, "intr_rate2": 3.20},
)


def _star_candidate() -> ProductCandidate:
    return ProductCandidate(
        product_name="KB Star 정기예금",
        base_data={
            "fin_prdt_nm": "KB Star 정기예금",
            "join_way": "인터넷,스마트폰",
        },
        option_list=STAR_OPTIONS,
    )


def test_passed_product_preserves_data_for_next_engine() -> None:
    candidate = _star_candidate()
    user_facts = {
        "deposit_amount": 10_000_000,
        "applicant_type": "individual",
    }

    result = route_product_candidates(
        [candidate],
        user_facts=user_facts,
        as_of=AS_OF,
        registry=REGISTRY,
    )

    assert len(result.forwardable) == 1
    assert result.rejected == ()
    assert result.needs_review == ()

    handoff = result.forwardable[0]
    assert handoff.product is candidate
    assert handoff.product.base_data["join_way"] == "인터넷,스마트폰"
    assert handoff.product.option_list is STAR_OPTIONS
    assert handoff.user_facts is user_facts
    assert handoff.rule_result.status is EvaluationStatus.PASS


def test_failed_product_is_rejected_with_options_preserved() -> None:
    candidate = _star_candidate()

    result = route_product_candidates(
        [candidate],
        user_facts={"deposit_amount": 999_999, "applicant_type": "individual"},
        as_of=AS_OF,
        registry=REGISTRY,
    )

    assert result.forwardable == ()
    assert result.needs_review == ()
    assert result.rejected[0].product.option_list == STAR_OPTIONS
    assert result.rejected[0].rule_result.failed_decisions[0].rule_code == (
        "KB_STAR_TD_MIN_DEPOSIT_AMOUNT"
    )


def test_unknown_product_is_separated_for_review() -> None:
    result = route_product_candidates(
        [_star_candidate()],
        user_facts={"deposit_amount": 1_000_000, "applicant_type": None},
        as_of=AS_OF,
        registry=REGISTRY,
    )

    assert result.forwardable == ()
    assert result.rejected == ()
    assert result.needs_review[0].status is EvaluationStatus.UNKNOWN


def test_multiple_candidates_are_routed_without_losing_order_or_options() -> None:
    super_options = (
        {"save_trm": "12", "intr_rate": 2.30, "intr_rate2": 2.40},
    )
    super_candidate = ProductCandidate(
        product_name="국민수퍼정기예금",
        base_data={"fin_prdt_nm": "국민수퍼정기예금"},
        option_list=super_options,
    )

    result = route_product_candidates(
        [_star_candidate(), super_candidate],
        user_facts={"deposit_amount": 1_000_000, "applicant_type": "individual"},
        as_of=AS_OF,
        registry=REGISTRY,
    )

    assert [item.product.product_name for item in result.forwardable] == [
        "KB Star 정기예금",
        "국민수퍼정기예금",
    ]
    assert result.forwardable[1].product.option_list is super_options


def test_default_registry_contains_friends_merged_packs() -> None:
    result = route_product_candidates(
        [_star_candidate()],
        user_facts={"deposit_amount": 1_000_000, "applicant_type": "individual"},
        as_of=AS_OF,
    )

    assert result.forwardable[0].product.product_name == "KB Star 정기예금"


def test_default_registry_contains_new_first_and_fourth_packs() -> None:
    result = route_product_candidates(
        [
            ProductCandidate(product_name="KB골든라이프연금예금"),
            ProductCandidate(product_name="일반정기예금"),
        ],
        user_facts={"deposit_amount": 1_000_000, "applicant_type": "individual"},
        as_of=AS_OF,
    )

    assert [item.product.product_name for item in result.forwardable] == [
        "KB골든라이프연금예금",
        "일반정기예금",
    ]
