from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.engines.affordability import AffordabilityVerdict
from app.schemas.property import (
    ListingStatus,
    PropertyCandidate,
    PropertyDataSourceType,
    PropertyRegion,
    PropertySearchCriteria,
    PropertySearchResult,
    PropertySourceMetadata,
    PropertyType,
    TransactionType,
)
from app.schemas.property_affordability import (
    PropertyAcquisitionFactsInput,
    PropertyAcquisitionProfileInput,
    PropertyAffordabilityAssessment,
    PropertyAffordabilitySearchRequest,
    PropertyAffordabilitySearchResponse,
)
from app.schemas.simulation import FinancialSnapshot, UserProfile


def _candidate() -> PropertyCandidate:
    return PropertyCandidate(
        listing_id="LISTING-1",
        source_listing_id="SOURCE-1",
        status=ListingStatus.ACTIVE,
        transaction_type=TransactionType.SALE,
        property_type=PropertyType.VILLA,
        region=PropertyRegion(
            sido_code="11",
            sigungu_code="11620",
            address_summary="Seoul",
        ),
        price_krw=Decimal("49000000"),
    )


def _search_result() -> PropertySearchResult:
    candidate = _candidate()
    return PropertySearchResult(
        search_snapshot_id=UUID("00000000-0000-0000-0000-000000000001"),
        searched_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
        data_as_of=datetime(2026, 7, 30, 0, tzinfo=UTC),
        source=PropertySourceMetadata(
            source_type=PropertyDataSourceType.MOCK,
            source_name="test",
            source_version="1",
        ),
        criteria=PropertySearchCriteria(region_codes=("11620",)),
        total_count=1,
        candidates=(candidate,),
    )


def _assessment() -> PropertyAffordabilityAssessment:
    return PropertyAffordabilityAssessment(
        candidate=_candidate(),
        verdict=AffordabilityVerdict.AFFORDABLE,
        minimum_total_purchase_cost=Decimal("50000000"),
        total_purchase_cost=Decimal("50000000"),
        usable_liquid_assets_before_purchase=Decimal("60000000"),
        required_loan_amount=Decimal(0),
        loan_funding_amount=Decimal(0),
        funding_gap=Decimal(0),
        engine_result={
            "listing_id": "LISTING-1",
            "verdict": "AFFORDABLE",
        },
        policy_sources=("source-a",),
    )


def test_listing_override_inherits_unspecified_default_facts() -> None:
    profile = PropertyAcquisitionProfileInput(
        default_property_facts=PropertyAcquisitionFactsInput(
            is_registered_housing=True,
            is_luxury_home=False,
            registration_and_legal_costs=Decimal("100000"),
        ),
        listing_overrides={
            "LISTING-1": PropertyAcquisitionFactsInput(
                registration_and_legal_costs=Decimal("200000")
            )
        },
    )

    facts = profile.facts_for("LISTING-1")

    assert facts.is_registered_housing is True
    assert facts.is_luxury_home is False
    assert facts.registration_and_legal_costs == Decimal("200000")


def test_request_rejects_a_global_required_loan_amount() -> None:
    from app.regulations.mortgage_limits import HousingStatus
    from app.schemas.simulation import LoanRequestInput

    with pytest.raises(ValidationError, match="calculated per listing"):
        PropertyAffordabilitySearchRequest(
            criteria=PropertySearchCriteria(region_codes=("11620",)),
            profile=UserProfile(age=30, annual_income=Decimal("60000000")),
            financial_snapshot=FinancialSnapshot(
                monthly_income=Decimal("5000000"),
                monthly_expense=Decimal("2000000"),
                liquid_assets=Decimal("30000000"),
            ),
            loan_request=LoanRequestInput(
                months=360,
                housing_status=HousingStatus.FIRST_HOME_BUYER,
                monthly_essential_expense=Decimal("2000000"),
                required_amount=Decimal("10000000"),
            ),
        )


def test_response_rejects_counts_that_do_not_match_assessments() -> None:
    with pytest.raises(ValidationError, match="verdict_counts"):
        PropertyAffordabilitySearchResponse(
            calculated_at=datetime(2026, 7, 30, 1, tzinfo=UTC),
            search_result=_search_result(),
            total_count=1,
            assessments=(_assessment(),),
            verdict_counts={"UNKNOWN": 1},
            policy_sources=("source-a",),
        )


def test_non_housing_cannot_claim_national_housing_scale() -> None:
    with pytest.raises(ValidationError, match="national housing"):
        PropertyAcquisitionFactsInput(
            is_registered_housing=False,
            is_national_housing_scale_override=True,
        )


def test_merged_listing_override_is_revalidated() -> None:
    with pytest.raises(ValidationError, match="national housing"):
        PropertyAcquisitionProfileInput(
            default_property_facts=PropertyAcquisitionFactsInput(
                is_registered_housing=False,
            ),
            listing_overrides={
                "LISTING-1": PropertyAcquisitionFactsInput(
                    is_national_housing_scale_override=True,
                )
            },
        )
