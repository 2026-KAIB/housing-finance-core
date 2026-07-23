from app.rule_engine.base import RuleDecision
from app.rule_engine.policy.context import PolicyEligibilityContext


class PolicyEffectivePeriodRule:
    """계산일 유효 정책만 사용한다 (DESIGN SSOT §20 적용 원칙)."""

    code = "POLICY_EFFECTIVE_PERIOD"

    def evaluate(self, context: PolicyEligibilityContext) -> RuleDecision:
        product = context.product
        end_date = product.effective_end_date
        started = product.effective_start_date <= context.as_of
        not_ended = end_date is None or context.as_of <= end_date
        passed = started and not_ended
        reasons: tuple[str, ...] = ()
        if not passed:
            end = end_date.isoformat() if end_date else "미정"
            reasons = (
                f"계산일({context.as_of.isoformat()})이 정책 적용기간"
                f"({product.effective_start_date.isoformat()}~{end}) 밖입니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=product.data_version
        )
