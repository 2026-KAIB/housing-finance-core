from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.rule_engine.common import ApplicantEligibilityCriteria, ApplicantSnapshot
from app.rule_engine.policy import (
    PolicyEligibilityContext,
    PolicyProduct,
    evaluate_policy_eligibility,
)

AS_OF = date(2026, 7, 23)

BASE_CRITERIA = ApplicantEligibilityCriteria(
    min_age=19,
    max_age=39,
    max_annual_income=Decimal("60000000"),
    max_annual_income_married=Decimal("80000000"),
    requires_first_home_buyer=True,
    requires_married=None,
    allowed_region_codes=("11", "41"),
    max_target_price=Decimal("600000000"),
    max_target_area_m2=Decimal("85"),
)

BASE_PRODUCT = PolicyProduct(
    policy_id="didimdol-2026",
    name="디딤돌대출(placeholder)",
    operating_institution="한국주택금융공사",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=date(2026, 12, 31),
    confirmed_date=date(2026, 7, 1),
    source_url="https://example.gov/didimdol",
    eligibility=BASE_CRITERIA,
    loan_limit=Decimal("400000000"),
    max_ltv=Decimal("0.70"),
    max_dti=Decimal("0.60"),
    max_dsr=Decimal("0.40"),
)

BASE_APPLICANT = ApplicantSnapshot(
    age=30,
    annual_income=Decimal("50000000"),
    is_married=False,
    is_first_home_buyer=True,
    region_code="11",
    target_price=Decimal("500000000"),
    target_area_m2=Decimal("59"),
)


def _context(
    *,
    product: PolicyProduct = BASE_PRODUCT,
    applicant: ApplicantSnapshot = BASE_APPLICANT,
    as_of: date = AS_OF,
) -> PolicyEligibilityContext:
    return PolicyEligibilityContext(as_of=as_of, applicant=applicant, product=product)


def test_fully_eligible_applicant_passes_every_rule() -> None:
    result = evaluate_policy_eligibility(_context())

    assert result.eligible is True
    assert result.reasons == ()
    assert {d.rule_code for d in result.decisions} == {
        "POLICY_EFFECTIVE_PERIOD",
        "APPLICANT_AGE",
        "APPLICANT_INCOME",
        "APPLICANT_MARRIAGE_STATUS",
        "APPLICANT_FIRST_HOME_BUYER",
        "APPLICANT_REGION",
        "APPLICANT_TARGET_PRICE_AREA",
    }


def test_effective_period_boundaries_are_inclusive() -> None:
    on_start = evaluate_policy_eligibility(_context(as_of=BASE_PRODUCT.effective_start_date))
    on_end = evaluate_policy_eligibility(_context(as_of=BASE_PRODUCT.effective_end_date))

    assert on_start.eligible is True
    assert on_end.eligible is True


def test_effective_period_rejects_dates_outside_range() -> None:
    before = evaluate_policy_eligibility(_context(as_of=date(2025, 12, 31)))
    after = evaluate_policy_eligibility(_context(as_of=date(2027, 1, 1)))

    assert before.eligible is False
    assert after.eligible is False


def test_open_ended_effective_period_has_no_end_date_limit() -> None:
    open_ended = replace(BASE_PRODUCT, effective_end_date=None)

    result = evaluate_policy_eligibility(_context(product=open_ended, as_of=date(2099, 1, 1)))

    assert result.eligible is True


def test_age_below_minimum_fails() -> None:
    applicant = replace(BASE_APPLICANT, age=18)

    result = evaluate_policy_eligibility(_context(applicant=applicant))

    assert result.eligible is False
    assert any(d.rule_code == "APPLICANT_AGE" for d in result.failed_decisions)


def test_age_at_boundaries_passes() -> None:
    at_min = evaluate_policy_eligibility(_context(applicant=replace(BASE_APPLICANT, age=19)))
    at_max = evaluate_policy_eligibility(_context(applicant=replace(BASE_APPLICANT, age=39)))

    assert at_min.eligible is True
    assert at_max.eligible is True


def test_married_applicant_uses_married_income_limit() -> None:
    applicant = replace(BASE_APPLICANT, is_married=True, annual_income=Decimal("70000000"))

    result = evaluate_policy_eligibility(_context(applicant=applicant))

    assert result.eligible is True


def test_married_applicant_still_rejected_above_married_limit() -> None:
    applicant = replace(BASE_APPLICANT, is_married=True, annual_income=Decimal("90000000"))

    result = evaluate_policy_eligibility(_context(applicant=applicant))

    assert result.eligible is False
    assert any(d.rule_code == "APPLICANT_INCOME" for d in result.failed_decisions)


def test_marriage_requirement_rejects_mismatched_status() -> None:
    product = replace(BASE_PRODUCT, eligibility=replace(BASE_CRITERIA, requires_married=True))

    result = evaluate_policy_eligibility(_context(product=product, applicant=BASE_APPLICANT))

    assert result.eligible is False
    assert any(d.rule_code == "APPLICANT_MARRIAGE_STATUS" for d in result.failed_decisions)


def test_first_home_buyer_requirement_rejects_existing_owner() -> None:
    applicant = replace(BASE_APPLICANT, is_first_home_buyer=False)

    result = evaluate_policy_eligibility(_context(applicant=applicant))

    assert result.eligible is False
    assert any(d.rule_code == "APPLICANT_FIRST_HOME_BUYER" for d in result.failed_decisions)


def test_region_outside_allowed_list_fails() -> None:
    applicant = replace(BASE_APPLICANT, region_code="26")

    result = evaluate_policy_eligibility(_context(applicant=applicant))

    assert result.eligible is False
    assert any(d.rule_code == "APPLICANT_REGION" for d in result.failed_decisions)


def test_unrestricted_region_accepts_any_code() -> None:
    product = replace(BASE_PRODUCT, eligibility=replace(BASE_CRITERIA, allowed_region_codes=None))
    applicant = replace(BASE_APPLICANT, region_code="99")

    result = evaluate_policy_eligibility(_context(product=product, applicant=applicant))

    assert result.eligible is True


def test_target_price_and_area_over_limit_reports_both_reasons() -> None:
    applicant = replace(
        BASE_APPLICANT, target_price=Decimal("700000000"), target_area_m2=Decimal("100")
    )

    result = evaluate_policy_eligibility(_context(applicant=applicant))

    price_area_decision = next(
        d for d in result.decisions if d.rule_code == "APPLICANT_TARGET_PRICE_AREA"
    )
    assert price_area_decision.passed is False
    assert len(price_area_decision.reasons) == 2


def test_source_version_is_stamped_on_every_decision() -> None:
    result = evaluate_policy_eligibility(_context())

    assert all(d.source_version == BASE_PRODUCT.data_version for d in result.decisions)


def test_data_version_prefers_regulatory_review_number_when_present() -> None:
    # DESIGN SSOT 부록 B-2/B-6: manual_pdf 소스는 심의필 번호가 확인일보다 우선하는 출처 근거.
    product = replace(
        BASE_PRODUCT, source_type="manual_pdf", regulatory_review_no="준법감시인 심의필 제2025-1호"
    )

    assert product.data_version == f"{product.policy_id}@준법감시인 심의필 제2025-1호"
