from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from app.engines.affordability import AffordabilityVerdict
from app.regulations.mortgage_limits import HousingStatus
from app.repositories import JsonPropertyListingRepository
from app.schemas.property import PropertySearchCriteria, PropertyType
from app.schemas.property_affordability import (
    PropertyAcquisitionFactsInput,
    PropertyAcquisitionProfileInput,
    PropertyAffordabilitySearchRequest,
)
from app.schemas.simulation import (
    FinancialSnapshot,
    LoanRequestInput,
    UserProfile,
)
from app.services.property_affordability_api import (
    build_property_affordability_ai_handoff,
    build_property_loan_profile,
    evaluate_property_search_affordability,
)

SEOUL = ZoneInfo("Asia/Seoul")
CALCULATED_AT = datetime(2026, 7, 30, 10, tzinfo=SEOUL)
DATASET = (
    Path(__file__).resolve().parents[2]
    / "sample_data"
    / "property_listings"
    / "property_listings.v1.json"
)


def _request(
    *,
    liquid_assets: Decimal = Decimal("100000000"),
    acquisition_profile: PropertyAcquisitionProfileInput | None = None,
    loan_request: LoanRequestInput | None = None,
) -> PropertyAffordabilitySearchRequest:
    return PropertyAffordabilitySearchRequest(
        criteria=PropertySearchCriteria(
            region_codes=("11620",),
            property_types=(PropertyType.VILLA,),
            max_price_krw=Decimal("50000000"),
            max_station_walk_minutes=10,
        ),
        profile=UserProfile(
            persona_name="PRIVATE-PERSONA",
            age=30,
            annual_income=Decimal("60000000"),
            is_first_home_buyer=True,
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            monthly_debt_payment=Decimal(0),
            liquid_assets=liquid_assets,
            emergency_reserve=Decimal("6000000"),
        ),
        loan_request=loan_request,
        acquisition_profile=acquisition_profile
        or PropertyAcquisitionProfileInput(
            buyer_is_corporation=False,
            household_home_count_after_purchase=1,
            default_property_facts=PropertyAcquisitionFactsInput(
                is_registered_housing=True,
                is_luxury_home=False,
                registration_and_legal_costs=Decimal("186000"),
            ),
        ),
    )


def _evaluate(
    payload: PropertyAffordabilitySearchRequest,
):
    return evaluate_property_search_affordability(
        payload,
        JsonPropertyListingRepository(DATASET),
        calculated_at=CALCULATED_AT,
        id_factory=lambda: UUID("00000000-0000-0000-0000-000000000001"),
    )


def test_search_and_affordability_returns_auditable_cash_purchase() -> None:
    response = _evaluate(_request())

    assert response.total_count == 1
    assessment = response.assessments[0]
    assert assessment.candidate.listing_id == "MOCK-GWANAK-001"
    assert assessment.verdict is AffordabilityVerdict.AFFORDABLE
    assert assessment.total_purchase_cost is not None
    assert assessment.total_purchase_cost > assessment.candidate.price_krw
    assert assessment.required_loan_amount == Decimal(0)
    assert assessment.engine_result["purchase_price"] == "49000000"
    assert response.verdict_counts == {"AFFORDABLE": 1}


def test_unknown_acquisition_facts_do_not_become_zero_costs() -> None:
    response = _evaluate(
        _request(
            acquisition_profile=PropertyAcquisitionProfileInput(),
        )
    )

    assessment = response.assessments[0]
    assert assessment.verdict is AffordabilityVerdict.UNKNOWN
    assert assessment.total_purchase_cost is None
    assert "buyer_is_corporation" in assessment.missing_inputs


def test_missing_loan_products_keeps_financing_unknown() -> None:
    response = _evaluate(
        _request(
            liquid_assets=Decimal("10000000"),
            loan_request=LoanRequestInput(
                months=360,
                housing_status=HousingStatus.FIRST_HOME_BUYER,
                monthly_essential_expense=Decimal("2000000"),
                credit_loan_balance=Decimal(0),
            ),
        )
    )

    assessment = response.assessments[0]
    assert assessment.verdict is AffordabilityVerdict.UNKNOWN
    assert assessment.required_loan_amount is not None
    assert assessment.required_loan_amount > 0
    assert assessment.loan_funding_amount is None
    assert "loan_product_candidates" in assessment.missing_inputs
    assert any("Safe DSR" in item for item in assessment.assumptions)


def test_loan_profile_preserves_regulation_date_and_derivation_assumptions() -> None:
    payload = _request(
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal("2000000"),
            regulation_as_of=date(2026, 7, 1),
        )
    )

    profile = build_property_loan_profile(payload)

    assert profile is not None
    assert profile.regulation_as_of == date(2026, 7, 1)
    assert any("Post-purchase monthly income" in item for item in profile.assumptions)
    assert any("Safe DSR" in item for item in profile.assumptions)


def test_ai_handoff_excludes_profile_and_raw_snapshot() -> None:
    response = _evaluate(_request())
    handoff = build_property_affordability_ai_handoff(response)
    encoded = handoff.model_dump_json()

    assert "PRIVATE-PERSONA" not in encoded
    assert "financial_snapshot" not in encoded
    assert not hasattr(handoff, "profile")
    assert handoff.items[0].listing_id == "MOCK-GWANAK-001"
    assert handoff.items[0].verdict is AffordabilityVerdict.AFFORDABLE
    assert any("without recalculating" in rule for rule in handoff.generation_rules)
