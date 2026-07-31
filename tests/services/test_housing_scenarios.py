"""SSOT §8 시나리오별 목표 주택가격.

고정하는 불변식:
1. 변동률은 §8.1 [B-6 확정] 표의 값이며 출처가 결과에 붙는다.
2. 취득 사실이 없으면 시나리오를 만들지 않는다 — 매매가만 쓰면 필요 자금을
   실제보다 작게 잡는다(§8.2).
3. 확률을 붙이지 않는다(§8.3).
4. 조기구매형 목표금액은 시나리오와 무관하게 같다 — 가격 위험은 미룰 때만 생긴다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.regulations.mortgage_limits import HousingStatus
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule
from app.schemas.simulation import (
    AcquisitionCostInput,
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SectionRunStatus,
    SimulationInput,
    UserProfile,
)
from app.services.housing_scenarios import (
    HOUSING_SCENARIO_RATES,
    SCENARIO_SOURCE,
    build_housing_cost_scenarios,
    scenario_price,
)
from app.services.simulation_orchestrator import run_simulation

AS_OF = date(2026, 7, 31)
CALCULATED_AT = datetime(2026, 7, 31, 9, tzinfo=UTC)
SIMULATION_ID = UUID("7c4e1a90-8d2b-4f16-9e05-31ab6c7d2f48")
CURRENT_PRICE = Decimal("500000000")


def _acquisition() -> AcquisitionCostInput:
    return AcquisitionCostInput(
        buyer_is_corporation=False,
        household_home_count_after_purchase=1,
        is_registered_housing=True,
        is_luxury_home=False,
        is_national_housing_scale_override=True,
        registration_and_legal_costs=Decimal("500000"),
    )


def _payload(acquisition: AcquisitionCostInput | None) -> SimulationInput:
    return SimulationInput(
        profile=UserProfile(
            age=34, annual_income=Decimal("60000000"), is_first_home_buyer=True
        ),
        housing_goal=HousingGoal(
            target_amount=CURRENT_PRICE,
            target_date=date(2028, 7, 31),
            region_code="11680",
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            liquid_assets=Decimal("150000000"),
            monthly_debt_payment=Decimal("300000"),
        ),
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal("1800000"),
        ),
        acquisition_costs=acquisition,
    )


# --------------------------------------------------------------------------
# 가격 공식
# --------------------------------------------------------------------------


def test_the_rate_table_matches_the_design_document() -> None:
    """§8.1 [B-6 확정] 표 그대로여야 한다. 값이 바뀌면 이 테스트가 깨진다."""
    table = {item.name: item.annual_rate for item in HOUSING_SCENARIO_RATES}

    assert table == {
        "현재 가격 유지": Decimal("0"),
        "완만한 상승": Decimal("0.02"),
        "보수적 상승": Decimal("0.04"),
        "스트레스": Decimal("0.04"),
    }


def test_a_zero_rate_leaves_the_price_untouched() -> None:
    assert scenario_price(
        CURRENT_PRICE, annual_rate=Decimal("0"), years=Decimal(2)
    ) == CURRENT_PRICE


def test_the_price_compounds_over_the_goal_period() -> None:
    """2% 2년이면 1.0404배다. 정수 연으로 끊지 않고 지수로 올린다."""
    price = scenario_price(CURRENT_PRICE, annual_rate=Decimal("0.02"), years=Decimal(2))

    assert price == Decimal("520200000")


def test_a_partial_year_is_not_rounded_up_to_a_whole_one() -> None:
    half = scenario_price(CURRENT_PRICE, annual_rate=Decimal("0.04"), years=Decimal("0.5"))
    full = scenario_price(CURRENT_PRICE, annual_rate=Decimal("0.04"), years=Decimal(1))

    assert CURRENT_PRICE < half < full


# --------------------------------------------------------------------------
# 시나리오 생성
# --------------------------------------------------------------------------


def test_without_acquisition_facts_no_scenario_is_built() -> None:
    """매매가만으로 세우면 필요 자금을 실제보다 작게 잡는다(§8.2)."""
    build = build_housing_cost_scenarios(_payload(None), as_of=AS_OF)

    assert build.scenarios == ()
    assert build.missing_inputs == ("acquisition_costs",)
    assert any("실제보다 작게 잡습니다" in reason for reason in build.reasons)


@pytest.fixture
def build():
    return build_housing_cost_scenarios(_payload(_acquisition()), as_of=AS_OF)


def test_four_scenarios_are_built_with_their_source(build) -> None:
    assert len(build.scenarios) == 4
    assert [item.name for item in build.scenarios] == [
        "현재 가격 유지",
        "완만한 상승",
        "보수적 상승",
        "스트레스",
    ]
    assert all(item.source_note == SCENARIO_SOURCE for item in build.scenarios)
    assert all(item.basis_date == AS_OF for item in build.scenarios)


def test_only_the_flat_scenario_is_the_baseline(build) -> None:
    """변동률 가정이 없는 유일한 시나리오다."""
    baselines = [item.name for item in build.scenarios if item.is_baseline]

    assert baselines == ["현재 가격 유지"]


def test_the_target_amount_includes_acquisition_costs(build) -> None:
    """§8.2 — 목표금액은 매매가가 아니라 총 구매 필요금액이다."""
    flat = next(item for item in build.scenarios if item.code == "CURRENT_PRICE")

    assert flat.asset_accumulation_total_cost > CURRENT_PRICE
    assert flat.early_purchase_total_cost == flat.asset_accumulation_total_cost


def test_buying_now_costs_the_same_in_every_scenario(build) -> None:
    """가격 변동 위험은 구매를 미룰 때만 생긴다."""
    early = {item.early_purchase_total_cost for item in build.scenarios}
    later = {item.asset_accumulation_total_cost for item in build.scenarios}

    assert len(early) == 1
    assert len(later) == 3, "보수적 상승과 스트레스는 가격 축이 같다"


def test_the_stress_scenario_says_where_its_rate_shock_lives(build) -> None:
    """가격은 보수적 상승과 같다. 다른 점이 어디서 적용되는지 밝혀야 한다."""
    stress = next(item for item in build.scenarios if item.code == "STRESS")
    conservative = next(item for item in build.scenarios if item.code == "CONSERVATIVE_RISE")

    assert stress.asset_accumulation_total_cost == (
        conservative.asset_accumulation_total_cost
    )
    assert any("생활 스트레스 구간에서 별도로" in item for item in stress.assumptions)


def test_no_probability_is_attached(build) -> None:
    joined = "\n".join(build.assumptions)

    assert "확률을 붙이지 않습니다" in joined
    for scenario in build.scenarios:
        text = "\n".join(scenario.assumptions)
        assert "확률" not in text
        assert "가능성이 높" not in text


def test_the_costs_are_priced_at_the_calculation_date_not_the_future(build) -> None:
    """미래 세율을 예측하지 않는다. 그 사실이 가정으로 남아야 한다."""
    for scenario in build.scenarios:
        assert any("산출 기준일의" in item for item in scenario.assumptions)


# --------------------------------------------------------------------------
# 오케스트레이터 연결
# --------------------------------------------------------------------------


MORTGAGE_PRODUCT = "KB 주택담보대출"


def _loan_pack() -> ProductRulePack:
    return ProductRulePack(
        product_name=MORTGAGE_PRODUCT,
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


def _loan_candidate() -> ProductCandidate:
    return ProductCandidate(
        product_name=MORTGAGE_PRODUCT,
        base_data={
            "source_type": "manual_pdf",
            "fin_prdt_nm": MORTGAGE_PRODUCT,
            "loan_lmt": "담보조사가격 및 소득금액에 따른 대출가능금액 이내",
        },
        option_list=(
            {
                "fin_prdt_nm": MORTGAGE_PRODUCT,
                "mrtg_type_nm": "아파트",
                "rpay_type_nm": "분할상환방식",
                "lend_rate_type_nm": "변동금리",
                "lend_rate_min": 3.0,
                "lend_rate_max": 3.0,
                "lend_rate_avg": 3.0,
            },
        ),
    )


def _simulate(payload: SimulationInput, **overrides):
    """전략 비교는 종합추천이 있어야 돈다 — 대출 후보를 함께 넘긴다."""
    return run_simulation(
        payload,
        simulation_id=SIMULATION_ID,
        as_of=AS_OF,
        calculated_at=CALCULATED_AT,
        loan_candidates=[_loan_candidate()],
        registry=ProductRulePackRegistry((_loan_pack(),)),
        **overrides,
    )


def test_the_strategy_section_stays_not_run_without_acquisition_facts() -> None:
    result = _simulate(_payload(None))

    assert result.strategy_comparison.run_status is SectionRunStatus.NOT_RUN
    assert "acquisition_costs" in result.strategy_comparison.missing_inputs
    assert "acquisition_costs" in result.missing_inputs


def test_an_explicit_scenario_list_wins_over_the_built_one() -> None:
    """호출자가 근거와 함께 넘긴 시나리오가 언제나 우선한다(§15)."""
    from app.engines.strategy.models import HousingCostScenario

    supplied = (
        HousingCostScenario(
            code="REGIONAL",
            name="지역 데이터 기반",
            early_purchase_total_cost=Decimal("400000000"),
            asset_accumulation_total_cost=Decimal("410000000"),
            is_baseline=True,
            source_note="지역 실거래 통계",
        ),
    )
    result = _simulate(_payload(_acquisition()), housing_scenarios=supplied)

    facts = result.strategy_comparison.result
    assert facts is not None
    names = {
        item["scenario"]["name"]
        for item in facts["asset_accumulation"]["scenarios"]
    }
    assert names == {"지역 데이터 기반"}
