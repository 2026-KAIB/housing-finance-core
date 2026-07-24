from app.rule_engine.base import Rule
from app.rule_engine.common import RuleSetResult, evaluate_all
from app.rule_engine.savings.context import SavingsEligibilityContext
from app.rule_engine.savings.rules import (
    DepositProtectionLimitRule,
    MaturityAlignmentRule,
    MembershipEligibilityRule,
    PaymentRangeRule,
    PreferentialConditionFeasibilityRule,
    RiskToleranceRule,
    SavingsEffectivePeriodRule,
)

DEFAULT_SAVINGS_RULES: tuple[Rule[SavingsEligibilityContext], ...] = (
    SavingsEffectivePeriodRule(),
    MembershipEligibilityRule(),
    PaymentRangeRule(),
    MaturityAlignmentRule(),
    RiskToleranceRule(),
    DepositProtectionLimitRule(),
    PreferentialConditionFeasibilityRule(),
)


def evaluate_savings_eligibility(
    context: SavingsEligibilityContext,
    rules: tuple[Rule[SavingsEligibilityContext], ...] = DEFAULT_SAVINGS_RULES,
) -> RuleSetResult:
    """예·적금상품 필터링을 판정한다 (DESIGN SSOT §11.1)."""
    return evaluate_all(rules, context)
