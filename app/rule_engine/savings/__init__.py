"""Savings product eligibility and preferential-rate rules."""

from app.rule_engine.savings.context import SavingsEligibilityContext
from app.rule_engine.savings.engine import DEFAULT_SAVINGS_RULES, evaluate_savings_eligibility
from app.rule_engine.savings.schemas import SavingsProduct

__all__ = [
    "DEFAULT_SAVINGS_RULES",
    "SavingsEligibilityContext",
    "SavingsProduct",
    "evaluate_savings_eligibility",
]

