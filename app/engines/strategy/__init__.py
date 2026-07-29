"""Asset-accumulation and early-purchase strategy comparison."""

from app.engines.strategy.engine import (
    compare_strategies,
    evaluate_strategy_scenario,
)
from app.engines.strategy.models import (
    DEFAULT_STRATEGY_POLICY,
    HousingCostScenario,
    StrategyCandidateInput,
    StrategyComparisonInput,
    StrategyComparisonResult,
    StrategyComparisonStatus,
    StrategyEvaluation,
    StrategyKind,
    StrategyPolicy,
    StrategyScenarioResult,
    StrategyScenarioStatus,
    StrategyScoreComponents,
    StrategyScoreStatus,
)

__all__ = [
    "DEFAULT_STRATEGY_POLICY",
    "HousingCostScenario",
    "StrategyCandidateInput",
    "StrategyComparisonInput",
    "StrategyComparisonResult",
    "StrategyComparisonStatus",
    "StrategyEvaluation",
    "StrategyKind",
    "StrategyPolicy",
    "StrategyScenarioResult",
    "StrategyScenarioStatus",
    "StrategyScoreComponents",
    "StrategyScoreStatus",
    "compare_strategies",
    "evaluate_strategy_scenario",
]
