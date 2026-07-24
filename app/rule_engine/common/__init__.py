"""Shared rule composition and decision helpers."""

from app.rule_engine.common.applicant import ApplicantEligibilityCriteria, ApplicantSnapshot
from app.rule_engine.common.applicant_rules import (
    DEFAULT_APPLICANT_RULES,
    ApplicantEligibilityContext,
)
from app.rule_engine.common.composition import evaluate_all
from app.rule_engine.common.results import RuleSetResult

__all__ = [
    "DEFAULT_APPLICANT_RULES",
    "ApplicantEligibilityContext",
    "ApplicantEligibilityCriteria",
    "ApplicantSnapshot",
    "RuleSetResult",
    "evaluate_all",
]

