from app.rule_engine.base import RuleDecision
from app.rule_engine.loans.context import LoanEligibilityContext


class LoanEffectivePeriodRule:
    """계산일 유효 상품만 사용한다 (DESIGN SSOT §20 적용 원칙)."""

    code = "LOAN_EFFECTIVE_PERIOD"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
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


class LoanLimitRule:
    """상품별 대출한도 (DESIGN SSOT §13.1-3).

    원천 데이터의 대출한도(`loan_lmt`)는 자유텍스트라 정규화 단계에서 파싱이
    실패할 수 있다(부록 B-5). `loan_limit=None`이면 판정 근거가 없는 것이지
    신청자 결격이 아니므로 통과시킨다.
    """

    code = "LOAN_PRODUCT_LIMIT"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        limit = context.product.loan_limit
        if limit is None:
            return RuleDecision(
                rule_code=self.code, passed=True, reasons=(), source_version=context.data_version
            )
        requested = context.requested_loan_amount
        passed = requested <= limit
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (f"요청 대출액 {requested}원이 상품 한도 {limit}원을 초과합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class LtvLimitRule:
    """LTV 조건 (DESIGN SSOT §13.1-4).

    LTV·DTI·DSR 상한은 상품 데이터가 아니라 별도 규제 상수표에서 매칭된다
    (부록 B-5). 매칭되지 않아 `max_ltv=None`이면 판정 근거가 없는 것이므로
    통과시킨다.
    """

    code = "LOAN_LTV_LIMIT"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        max_ltv = context.product.max_ltv
        if max_ltv is None:
            return RuleDecision(
                rule_code=self.code, passed=True, reasons=(), source_version=context.data_version
            )
        passed = context.computed_ltv <= max_ltv
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (f"LTV {context.computed_ltv}가 한도 {max_ltv}를 초과합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class DtiLimitRule:
    """DTI 조건. 상한 매칭 여부는 LtvLimitRule과 동일 (DESIGN SSOT §13.1-4 / 부록 B-5)."""

    code = "LOAN_DTI_LIMIT"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        max_dti = context.product.max_dti
        if max_dti is None:
            return RuleDecision(
                rule_code=self.code, passed=True, reasons=(), source_version=context.data_version
            )
        passed = context.computed_dti <= max_dti
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (f"DTI {context.computed_dti}가 한도 {max_dti}를 초과합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class DsrLimitRule:
    """DSR 조건. 기존+신규 대출 원리금 포함 값이어야 한다 (DESIGN SSOT §13.1-4 / §13.2 / A-12).

    상한 매칭 여부는 LtvLimitRule과 동일 (부록 B-5).
    """

    code = "LOAN_DSR_LIMIT"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        max_dsr = context.product.max_dsr
        if max_dsr is None:
            return RuleDecision(
                rule_code=self.code, passed=True, reasons=(), source_version=context.data_version
            )
        passed = context.computed_dsr <= max_dsr
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (f"DSR {context.computed_dsr}가 한도 {max_dsr}를 초과합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class EquityAdequacyRule:
    """필요 자기자본 보유 여부 (DESIGN SSOT §13.1-5 / §9.2)."""

    code = "LOAN_EQUITY_ADEQUACY"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        passed = context.equity_available >= context.equity_target
        reasons: tuple[str, ...] = ()
        if not passed:
            shortfall = context.equity_target - context.equity_available
            reasons = (f"보유 자기자본이 목표 대비 {shortfall}원 부족합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class PostPurchaseEmergencyFundRule:
    """구매 후 비상자금 유지 여부 (DESIGN SSOT §13.1-6)."""

    code = "LOAN_POST_PURCHASE_EMERGENCY_FUND"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        passed = context.post_purchase_emergency_fund >= 0
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = ("구매 후 비상자금이 고갈되어(음수) 유지 조건을 충족하지 못합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class PostPurchaseCashflowBufferRule:
    """구매 후 월 현금흐름 ≥ Buffer (DESIGN SSOT §13.1-7 / A-8)."""

    code = "LOAN_POST_PURCHASE_CASHFLOW_BUFFER"

    def evaluate(self, context: LoanEligibilityContext) -> RuleDecision:
        passed = context.post_purchase_monthly_cashflow >= context.buffer_target
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (
                f"구매 후 월 잉여자금 {context.post_purchase_monthly_cashflow}원이"
                f" 최소 여유자금(Buffer) {context.buffer_target}원에 못 미칩니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )
