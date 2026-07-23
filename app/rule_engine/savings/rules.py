from app.rule_engine.base import RuleDecision
from app.rule_engine.savings.context import SavingsEligibilityContext


class SavingsEffectivePeriodRule:
    """계산일 유효 상품만 사용한다 (DESIGN SSOT §20 적용 원칙)."""

    code = "SAVINGS_EFFECTIVE_PERIOD"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        product = context.product
        end_date = product.effective_end_date
        started = product.effective_start_date <= context.as_of
        not_ended = end_date is None or context.as_of <= end_date
        passed = started and not_ended
        reasons: tuple[str, ...] = ()
        if not passed:
            end = end_date.isoformat() if end_date else "미정"
            reasons = (
                f"계산일({context.as_of.isoformat()})이 상품 적용기간"
                f"({product.effective_start_date.isoformat()}~{end}) 밖입니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=product.data_version
        )


class MembershipEligibilityRule:
    """가입 대상 해당 여부 (DESIGN SSOT §11.1)."""

    code = "SAVINGS_MEMBERSHIP_ELIGIBILITY"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        passed = context.is_membership_eligible
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = ("가입 대상 조건에 해당하지 않습니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class PaymentRangeRule:
    """납입액이 상품 범위 내인지 확인 (DESIGN SSOT §11.1)."""

    code = "SAVINGS_PAYMENT_RANGE"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        product = context.product
        payment = context.planned_monthly_payment
        passed = product.min_monthly_payment <= payment <= product.max_monthly_payment
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (
                f"월 납입액 {context.planned_monthly_payment}원이 상품 허용범위"
                f"({product.min_monthly_payment}~{product.max_monthly_payment}원) 밖입니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class MaturityAlignmentRule:
    """만기가 자금 필요시점 이전·해당 시점에 도래하는지 확인 (DESIGN SSOT §11.1)."""

    code = "SAVINGS_MATURITY_ALIGNMENT"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        passed = context.product_maturity_date <= context.fund_needed_date
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (
                f"상품 만기({context.product_maturity_date.isoformat()})가 자금 필요시점"
                f"({context.fund_needed_date.isoformat()})보다 늦습니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class RiskToleranceRule:
    """위험성향 적합 여부. 원금손실 가능 상품은 사용자 감내 의사가 필요 (DESIGN SSOT §11.1)."""

    code = "SAVINGS_RISK_TOLERANCE"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        passed = context.product.is_principal_protected or context.accepts_principal_risk
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = ("원금손실 가능 상품이며 사용자의 위험성향과 맞지 않습니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class DepositProtectionLimitRule:
    """예금자보호 대상 상품은 예치액이 보호 한도 이하여야 한다 (DESIGN SSOT §11.1 / §12.1)."""

    code = "SAVINGS_DEPOSIT_PROTECTION_LIMIT"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        if not context.product.is_deposit_protected:
            return RuleDecision(
                rule_code=self.code, passed=True, reasons=(), source_version=context.data_version
            )
        passed = context.projected_deposit_at_institution <= context.deposit_protection_limit
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (
                f"동일 금융회사 예상 예치액 {context.projected_deposit_at_institution}원이"
                f" 예금자보호 한도 {context.deposit_protection_limit}원을 초과합니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class PreferentialConditionFeasibilityRule:
    """우대조건을 현실적으로 충족할 수 있는지 확인 (DESIGN SSOT §11.1 / A-9)."""

    code = "SAVINGS_PREFERENTIAL_FEASIBILITY"

    def evaluate(self, context: SavingsEligibilityContext) -> RuleDecision:
        passed = context.preferential_conditions_feasible
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = ("우대조건을 현실적으로 충족하기 어렵습니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )
