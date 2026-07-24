from app.rule_engine.base import Rule
from app.rule_engine.common import DEFAULT_APPLICANT_RULES, RuleSetResult, evaluate_all
from app.rule_engine.policy.context import PolicyEligibilityContext
from app.rule_engine.policy.rules import PolicyEffectivePeriodRule

DEFAULT_POLICY_RULES: tuple[Rule[PolicyEligibilityContext], ...] = (
    PolicyEffectivePeriodRule(),
    *DEFAULT_APPLICANT_RULES,
)


def evaluate_policy_eligibility(
    context: PolicyEligibilityContext,
    rules: tuple[Rule[PolicyEligibilityContext], ...] = DEFAULT_POLICY_RULES,
) -> RuleSetResult:
    """정책상품 자격조건을 판정한다 (DESIGN SSOT §13.1-1,2 / §20)."""
    return evaluate_all(rules, context)
