from app.rule_engine.base import Rule
from app.rule_engine.common import DEFAULT_APPLICANT_RULES, RuleSetResult, evaluate_all
from app.rule_engine.loans.context import LoanEligibilityContext
from app.rule_engine.loans.rules import (
    DsrLimitRule,
    DtiLimitRule,
    EquityAdequacyRule,
    LoanEffectivePeriodRule,
    LoanLimitRule,
    LtvLimitRule,
    PostPurchaseCashflowBufferRule,
    PostPurchaseEmergencyFundRule,
)

DEFAULT_LOAN_RULES: tuple[Rule[LoanEligibilityContext], ...] = (
    LoanEffectivePeriodRule(),
    *DEFAULT_APPLICANT_RULES,
    LoanLimitRule(),
    LtvLimitRule(),
    DtiLimitRule(),
    DsrLimitRule(),
    EquityAdequacyRule(),
    PostPurchaseEmergencyFundRule(),
    PostPurchaseCashflowBufferRule(),
)


def evaluate_loan_eligibility(
    context: LoanEligibilityContext,
    rules: tuple[Rule[LoanEligibilityContext], ...] = DEFAULT_LOAN_RULES,
) -> RuleSetResult:
    """대출상품 필수조건을 판정한다 (DESIGN SSOT §13.1). 하나라도 미충족 시 점수와 무관하게 제외."""
    return evaluate_all(rules, context)
