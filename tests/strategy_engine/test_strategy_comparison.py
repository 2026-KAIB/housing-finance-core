from datetime import date
from decimal import Decimal

import pytest

from app.engines.strategy import (
    HousingCostScenario,
    StrategyCandidateInput,
    StrategyComparisonInput,
    StrategyComparisonStatus,
    StrategyKind,
    StrategyScenarioStatus,
    StrategyScoreStatus,
    compare_strategies,
    evaluate_strategy_scenario,
)

_AS_OF = date(2026, 7, 30)
_TARGET = date(2028, 7, 30)
_BASE = HousingCostScenario(
    code="BASE",
    name="현재 가격 유지",
    early_purchase_total_cost=Decimal("300000000"),
    asset_accumulation_total_cost=Decimal("300000000"),
    is_baseline=True,
)
_UP = HousingCostScenario(
    code="UP",
    name="완만한 상승",
    early_purchase_total_cost=Decimal("310000000"),
    asset_accumulation_total_cost=Decimal("330000000"),
)


def _candidate(kind: StrategyKind, **overrides: object) -> StrategyCandidateInput:
    defaults: dict[str, object] = {
        "kind": kind,
        "planned_purchase_date": (
            date(2028, 7, 30)
            if kind is StrategyKind.ASSET_ACCUMULATION
            else _AS_OF
        ),
        "available_equity": Decimal("100000000"),
        "loan_capacity": Decimal("230000000"),
        "monthly_savings_amount": Decimal("1000000"),
        "monthly_loan_payment": Decimal("900000"),
        "total_financial_cost": Decimal("80000000"),
        "expected_net_savings_interest": Decimal("1000000"),
        "cashflow_stability_score": Decimal("0.8"),
        "plan_flexibility_score": Decimal("0.6"),
    }
    defaults.update(overrides)
    return StrategyCandidateInput(**defaults)  # type: ignore[arg-type]


def test_known_equity_and_loan_produce_pass_and_fail_amounts() -> None:
    candidate = _candidate(
        StrategyKind.ASSET_ACCUMULATION,
        available_equity=Decimal("100000000"),
        loan_capacity=Decimal("200000000"),
    )

    passed = evaluate_strategy_scenario(candidate, _BASE)
    failed = evaluate_strategy_scenario(candidate, _UP)

    assert passed.status is StrategyScenarioStatus.PASS
    assert passed.required_equity == Decimal("100000000")
    assert passed.expected_loan_amount == Decimal("200000000")
    assert passed.coverage_ratio == Decimal(1)
    assert failed.status is StrategyScenarioStatus.FAIL
    assert failed.funding_shortfall == Decimal("30000000")
    assert failed.coverage_ratio == Decimal("0.9090909090909090909090909091")


def test_unknown_loan_is_not_failed_unless_equity_alone_is_enough() -> None:
    unknown = evaluate_strategy_scenario(
        _candidate(
            StrategyKind.ASSET_ACCUMULATION,
            available_equity=Decimal("100000000"),
            loan_capacity=None,
        ),
        _BASE,
    )
    equity_only = evaluate_strategy_scenario(
        _candidate(
            StrategyKind.ASSET_ACCUMULATION,
            available_equity=Decimal("350000000"),
            loan_capacity=None,
        ),
        _BASE,
    )

    assert unknown.status is StrategyScenarioStatus.UNKNOWN
    assert unknown.funding_shortfall is None
    assert unknown.missing_inputs == ("loan_capacity",)
    assert equity_only.status is StrategyScenarioStatus.PASS
    assert equity_only.expected_loan_amount == 0


def test_complete_score_uses_official_weights_and_selects_leader() -> None:
    result = compare_strategies(
        StrategyComparisonInput(
            as_of=_AS_OF,
            target_purchase_date=_TARGET,
            housing_scenarios=(_BASE,),
            asset_accumulation=_candidate(
                StrategyKind.ASSET_ACCUMULATION,
                total_financial_cost=Decimal("50000000"),
                cashflow_stability_score=Decimal("0.8"),
                plan_flexibility_score=Decimal("0.6"),
            ),
            early_purchase=_candidate(
                StrategyKind.EARLY_PURCHASE,
                total_financial_cost=Decimal("80000000"),
                cashflow_stability_score=Decimal("0.5"),
                plan_flexibility_score=Decimal("0.8"),
            ),
        )
    )

    assert result.asset_accumulation.score == Decimal("91.00")
    assert result.early_purchase.score == Decimal("65.500")
    assert result.status is StrategyComparisonStatus.COMPLETE
    assert result.leading_strategy is StrategyKind.ASSET_ACCUMULATION
    assert result.recommended_strategy is StrategyKind.ASSET_ACCUMULATION


def test_missing_cashflow_is_provisional_but_not_zero() -> None:
    result = compare_strategies(
        StrategyComparisonInput(
            as_of=_AS_OF,
            target_purchase_date=_TARGET,
            housing_scenarios=(_BASE,),
            asset_accumulation=_candidate(
                StrategyKind.ASSET_ACCUMULATION,
                cashflow_stability_score=None,
            ),
            early_purchase=_candidate(
                StrategyKind.EARLY_PURCHASE,
                cashflow_stability_score=None,
            ),
        )
    )

    assert result.asset_accumulation.score_status is StrategyScoreStatus.PROVISIONAL
    assert result.asset_accumulation.score_completeness == Decimal("0.75")
    assert "cashflow_stability" in result.asset_accumulation.missing_score_components
    assert result.status is StrategyComparisonStatus.PROVISIONAL
    assert result.recommended_strategy is None


def test_an_unattainable_strategy_cannot_win_on_other_scores() -> None:
    result = compare_strategies(
        StrategyComparisonInput(
            as_of=_AS_OF,
            target_purchase_date=_TARGET,
            housing_scenarios=(_BASE,),
            asset_accumulation=_candidate(
                StrategyKind.ASSET_ACCUMULATION,
                available_equity=Decimal("10000000"),
                loan_capacity=Decimal("10000000"),
                total_financial_cost=Decimal("10000000"),
                cashflow_stability_score=Decimal(1),
                plan_flexibility_score=Decimal(1),
            ),
            early_purchase=_candidate(
                StrategyKind.EARLY_PURCHASE,
                available_equity=Decimal("100000000"),
                loan_capacity=Decimal("200000000"),
                total_financial_cost=Decimal("80000000"),
                cashflow_stability_score=Decimal("0.1"),
                plan_flexibility_score=Decimal("0.1"),
            ),
        )
    )

    assert result.asset_accumulation.score > result.early_purchase.score
    assert result.asset_accumulation.attainable_count == 0
    assert result.leading_strategy is StrategyKind.EARLY_PURCHASE
    assert result.recommended_strategy is StrategyKind.EARLY_PURCHASE


def test_too_many_missing_components_make_score_unavailable() -> None:
    result = compare_strategies(
        StrategyComparisonInput(
            as_of=_AS_OF,
            target_purchase_date=_TARGET,
            housing_scenarios=(_BASE,),
            asset_accumulation=_candidate(
                StrategyKind.ASSET_ACCUMULATION,
                loan_capacity=None,
                total_financial_cost=None,
                cashflow_stability_score=None,
                plan_flexibility_score=None,
            ),
            early_purchase=_candidate(
                StrategyKind.EARLY_PURCHASE,
                total_financial_cost=None,
                cashflow_stability_score=None,
                plan_flexibility_score=None,
            ),
        )
    )

    assert result.asset_accumulation.score is None
    assert result.asset_accumulation.score_status is StrategyScoreStatus.UNAVAILABLE
    assert result.status is StrategyComparisonStatus.UNAVAILABLE


def test_exactly_one_baseline_scenario_is_required() -> None:
    with pytest.raises(ValueError, match="정확히 하나"):
        StrategyComparisonInput(
            as_of=_AS_OF,
            target_purchase_date=_TARGET,
            housing_scenarios=(_UP,),
            asset_accumulation=_candidate(StrategyKind.ASSET_ACCUMULATION),
            early_purchase=_candidate(StrategyKind.EARLY_PURCHASE),
        )
