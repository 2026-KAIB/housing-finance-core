from typing import Protocol

from app.rule_engine.base import RuleDecision
from app.rule_engine.common.applicant import ApplicantEligibilityCriteria, ApplicantSnapshot


class ApplicantEligibilityContext(Protocol):
    """정책·대출 컨텍스트가 신청자격 규칙을 쓰려면 갖춰야 하는 최소 형태."""

    applicant: ApplicantSnapshot
    eligibility_criteria: ApplicantEligibilityCriteria
    data_version: str


class ApplicantAgeRule:
    """연령 자격조건 (DESIGN SSOT §13.1-1)."""

    code = "APPLICANT_AGE"

    def evaluate(self, context: ApplicantEligibilityContext) -> RuleDecision:
        applicant, criteria = context.applicant, context.eligibility_criteria
        too_young = criteria.min_age is not None and applicant.age < criteria.min_age
        too_old = criteria.max_age is not None and applicant.age > criteria.max_age
        passed = not (too_young or too_old)
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (
                f"연령 {applicant.age}세가 자격조건"
                f"(최소 {criteria.min_age}, 최대 {criteria.max_age}) 범위를 벗어났습니다.",
            )
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class ApplicantIncomeRule:
    """소득 자격조건. 혼인 시 부부합산 한도가 별도 지정되면 우선 적용 (DESIGN SSOT §13.1-1)."""

    code = "APPLICANT_INCOME"

    def evaluate(self, context: ApplicantEligibilityContext) -> RuleDecision:
        applicant, criteria = context.applicant, context.eligibility_criteria
        limit = criteria.max_annual_income
        if applicant.is_married and criteria.max_annual_income_married is not None:
            limit = criteria.max_annual_income_married
        passed = limit is None or applicant.annual_income <= limit
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (f"연소득 {applicant.annual_income}원이 소득 한도 {limit}원을 초과합니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class ApplicantMarriageRule:
    """혼인 요건. `requires_married=None`이면 조건 없음 (DESIGN SSOT §13.1-1)."""

    code = "APPLICANT_MARRIAGE_STATUS"

    def evaluate(self, context: ApplicantEligibilityContext) -> RuleDecision:
        applicant, criteria = context.applicant, context.eligibility_criteria
        required = criteria.requires_married
        passed = required is None or required == applicant.is_married
        reasons: tuple[str, ...] = ()
        if not passed:
            expected = "기혼" if required else "미혼"
            reasons = (f"이 상품은 {expected} 신청자만 대상입니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class ApplicantFirstHomeBuyerRule:
    """무주택 요건 (DESIGN SSOT §13.1-1)."""

    code = "APPLICANT_FIRST_HOME_BUYER"

    def evaluate(self, context: ApplicantEligibilityContext) -> RuleDecision:
        applicant, criteria = context.applicant, context.eligibility_criteria
        passed = not criteria.requires_first_home_buyer or applicant.is_first_home_buyer
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = ("이 상품은 무주택 세대주만 신청할 수 있습니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class ApplicantRegionRule:
    """지역 자격조건. `allowed_region_codes=None`이면 전국 대상 (DESIGN SSOT §13.1-1)."""

    code = "APPLICANT_REGION"

    def evaluate(self, context: ApplicantEligibilityContext) -> RuleDecision:
        applicant, criteria = context.applicant, context.eligibility_criteria
        allowed = criteria.allowed_region_codes
        passed = allowed is None or applicant.region_code in allowed
        reasons: tuple[str, ...] = ()
        if not passed:
            reasons = (f"거주 지역({applicant.region_code})이 대상 지역이 아닙니다.",)
        return RuleDecision(
            rule_code=self.code, passed=passed, reasons=reasons, source_version=context.data_version
        )


class ApplicantTargetPriceAreaRule:
    """대상 주택가격·면적 조건 (DESIGN SSOT §13.1-2)."""

    code = "APPLICANT_TARGET_PRICE_AREA"

    def evaluate(self, context: ApplicantEligibilityContext) -> RuleDecision:
        applicant, criteria = context.applicant, context.eligibility_criteria
        max_price = criteria.max_target_price
        max_area = criteria.max_target_area_m2
        target_area = applicant.target_area_m2
        price_ok = max_price is None or applicant.target_price <= max_price
        area_ok = max_area is None or target_area is None or target_area <= max_area
        passed = price_ok and area_ok
        reasons: list[str] = []
        if not price_ok:
            reasons.append(f"목표 주택가격 {applicant.target_price}원이 한도 {max_price}원 초과.")
        if not area_ok:
            reasons.append(f"목표 면적 {target_area}㎡가 한도 {max_area}㎡ 초과.")
        return RuleDecision(
            rule_code=self.code,
            passed=passed,
            reasons=tuple(reasons),
            source_version=context.data_version,
        )


DEFAULT_APPLICANT_RULES = (
    ApplicantAgeRule(),
    ApplicantIncomeRule(),
    ApplicantMarriageRule(),
    ApplicantFirstHomeBuyerRule(),
    ApplicantRegionRule(),
    ApplicantTargetPriceAreaRule(),
)
