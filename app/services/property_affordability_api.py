"""Application service for structured search followed by per-listing affordability."""

from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.data_pipeline.adapters.loan_engine_adapter import BorrowerFinancialState
from app.engines.affordability import PropertyAffordabilityResult
from app.repositories.property_listing import PropertyListingRepository
from app.rule_engine.product_packs.handoff import ProductCandidate as LoanProductCandidate
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.schemas.property import PropertyCandidate
from app.schemas.property_affordability import (
    PropertyAffordabilityAIHandoff,
    PropertyAffordabilityAIItem,
    PropertyAffordabilityAssessment,
    PropertyAffordabilitySearchRequest,
    PropertyAffordabilitySearchResponse,
)
from app.services.cashflow_diagnosis import diagnose_financial_snapshot
from app.services.property_affordability import (
    PropertyLoanProfile,
    assess_property_candidates,
    build_property_affordability_case,
)
from app.services.property_search import search_properties
from app.services.simulation_result import to_json_value


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def build_property_loan_profile(
    payload: PropertyAffordabilitySearchRequest,
) -> PropertyLoanProfile | None:
    """Build shared borrower facts; the requested amount is recalculated per listing."""

    loan_request = payload.loan_request
    if loan_request is None:
        return None

    snapshot = payload.financial_snapshot
    assumptions: list[str] = []

    existing_annual_debt_service = loan_request.existing_annual_debt_service
    if existing_annual_debt_service is None:
        existing_annual_debt_service = snapshot.monthly_debt_payment * Decimal(12)
        if existing_annual_debt_service > 0:
            assumptions.append(
                "Existing annual debt service was derived as monthly debt payment times 12."
            )

    post_purchase_income = loan_request.post_purchase_monthly_income
    if post_purchase_income is None:
        post_purchase_income = snapshot.monthly_income
        assumptions.append(
            "Post-purchase monthly income was assumed to equal current monthly income."
        )

    post_purchase_expense = loan_request.post_purchase_monthly_expense
    if post_purchase_expense is None:
        post_purchase_expense = snapshot.monthly_expense
        assumptions.append(
            "Post-purchase monthly expense was assumed to equal current monthly expense."
        )

    borrower = BorrowerFinancialState(
        annual_income=payload.resolved_annual_income,
        existing_annual_debt_service=existing_annual_debt_service,
        post_purchase_monthly_income=post_purchase_income,
        post_purchase_monthly_expense=post_purchase_expense,
        other_existing_monthly_debt_service=snapshot.monthly_debt_payment,
        monthly_essential_expense=loan_request.monthly_essential_expense,
        safe_dsr=loan_request.safe_dsr,
        existing_annual_interest=loan_request.existing_annual_interest,
    )
    assumptions.append(
        f"Safe DSR {loan_request.safe_dsr * 100:.0f}% is an internal recommendation "
        "threshold, not a statutory maximum."
    )

    user_facts: dict[str, object] = {
        "age": payload.profile.age,
        "annual_income": payload.resolved_annual_income,
    }
    if payload.profile.employment_type is not None:
        user_facts["employment_type"] = payload.profile.employment_type

    return PropertyLoanProfile(
        borrower=borrower,
        housing_status=loan_request.housing_status,
        months=loan_request.months,
        user_facts=user_facts,
        rate_selection=loan_request.rate_selection,
        for_house_purchase=loan_request.for_house_purchase,
        credit_loan_balance=loan_request.credit_loan_balance,
        regulation_as_of=loan_request.regulation_as_of,
        assumptions=tuple(assumptions),
    )


def _assessment(
    result: PropertyAffordabilityResult,
    *,
    candidate: PropertyCandidate,
) -> PropertyAffordabilityAssessment:
    engine_result = to_json_value(result)
    if not isinstance(engine_result, dict):
        raise TypeError("property affordability result must serialize to a JSON object")
    selected_products = (
        ()
        if result.selected_loan_plan is None
        else result.selected_loan_plan.product_names
    )
    return PropertyAffordabilityAssessment(
        candidate=candidate,
        verdict=result.verdict,
        minimum_total_purchase_cost=result.minimum_total_purchase_cost,
        total_purchase_cost=result.total_purchase_cost,
        usable_liquid_assets_before_purchase=result.usable_liquid_assets_before_purchase,
        required_loan_amount=result.required_loan_amount,
        selected_loan_products=selected_products,
        loan_funding_amount=result.loan_funding_amount,
        funding_gap=result.funding_gap,
        monthly_loan_payment=result.monthly_loan_payment,
        post_purchase_monthly_surplus=result.post_purchase_monthly_surplus,
        stress_monthly_surplus=result.stress_monthly_surplus,
        engine_result=engine_result,
        missing_inputs=result.missing_inputs,
        reasons=result.reasons,
        assumptions=result.assumptions,
        policy_sources=result.policy_sources,
    )


def evaluate_property_search_affordability(
    payload: PropertyAffordabilitySearchRequest,
    repository: PropertyListingRepository,
    *,
    calculated_at: datetime,
    loan_candidates: Sequence[LoanProductCandidate] = (),
    registry: ProductRulePackRegistry | None = None,
    id_factory: Callable[[], UUID] = uuid4,
) -> PropertyAffordabilitySearchResponse:
    """Search one provider snapshot and run the established engines for every match."""

    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("calculated_at must include a timezone")

    search_result = search_properties(
        repository,
        payload.criteria,
        now=lambda: calculated_at,
        id_factory=id_factory,
    )
    cashflow_result = diagnose_financial_snapshot(
        payload.financial_snapshot,
        as_of=calculated_at.date(),
    )
    loan_profile = build_property_loan_profile(payload)
    acquisition = payload.acquisition_profile
    cases = tuple(
        build_property_affordability_case(
            candidate,
            as_of=calculated_at.date(),
            buyer_is_corporation=acquisition.buyer_is_corporation,
            household_home_count_after_purchase=(
                acquisition.household_home_count_after_purchase
            ),
            **acquisition.facts_for(candidate.listing_id).model_dump(),
        )
        for candidate in search_result.candidates
    )
    results = assess_property_candidates(
        cases,
        cashflow_result=cashflow_result,
        loan_profile=loan_profile,
        loan_candidates=loan_candidates,
        registry=registry,
    )
    assessments = tuple(
        _assessment(result, candidate=candidate)
        for candidate, result in zip(search_result.candidates, results, strict=True)
    )

    verdict_counts: dict[str, int] = {}
    for assessment in assessments:
        key = assessment.verdict.value
        verdict_counts[key] = verdict_counts.get(key, 0) + 1

    return PropertyAffordabilitySearchResponse(
        calculated_at=calculated_at,
        search_result=search_result,
        total_count=len(assessments),
        assessments=assessments,
        verdict_counts=verdict_counts,
        missing_inputs=_dedupe(
            [
                item
                for assessment in assessments
                for item in assessment.missing_inputs
            ]
        ),
        policy_sources=_dedupe(
            [
                item
                for assessment in assessments
                for item in assessment.policy_sources
            ]
        ),
    )


def build_property_affordability_ai_handoff(
    response: PropertyAffordabilitySearchResponse,
) -> PropertyAffordabilityAIHandoff:
    """Strip request/profile data and expose only verified narrative facts."""

    return PropertyAffordabilityAIHandoff(
        search_snapshot_id=response.search_result.search_snapshot_id,
        calculated_at=response.calculated_at,
        data_as_of=response.search_result.data_as_of,
        source=response.search_result.source,
        items=tuple(
            PropertyAffordabilityAIItem(
                listing_id=assessment.candidate.listing_id,
                property_name=assessment.candidate.property_name,
                address_summary=assessment.candidate.region.address_summary,
                price_krw=assessment.candidate.price_krw,
                nearest_station_walk_minutes=(
                    assessment.candidate.nearest_walk_minutes
                ),
                verdict=assessment.verdict,
                minimum_total_purchase_cost=assessment.minimum_total_purchase_cost,
                total_purchase_cost=assessment.total_purchase_cost,
                usable_liquid_assets_before_purchase=(
                    assessment.usable_liquid_assets_before_purchase
                ),
                required_loan_amount=assessment.required_loan_amount,
                selected_loan_products=assessment.selected_loan_products,
                loan_funding_amount=assessment.loan_funding_amount,
                funding_gap=assessment.funding_gap,
                monthly_loan_payment=assessment.monthly_loan_payment,
                post_purchase_monthly_surplus=(
                    assessment.post_purchase_monthly_surplus
                ),
                stress_monthly_surplus=assessment.stress_monthly_surplus,
                missing_inputs=assessment.missing_inputs,
                reasons=assessment.reasons,
                assumptions=assessment.assumptions,
                policy_sources=assessment.policy_sources,
            )
            for assessment in response.assessments
        ),
        missing_inputs=response.missing_inputs,
        policy_sources=response.policy_sources,
    )


__all__ = [
    "build_property_affordability_ai_handoff",
    "build_property_loan_profile",
    "evaluate_property_search_affordability",
]
