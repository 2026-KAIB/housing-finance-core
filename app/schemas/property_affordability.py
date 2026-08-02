"""Versioned API contracts for property-level affordability evaluation."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.engines.affordability import AffordabilityVerdict
from app.schemas.property import (
    PropertyCandidate,
    PropertySearchCriteria,
    PropertySearchResult,
    PropertySourceMetadata,
)
from app.schemas.simulation import (
    FinancialSnapshot,
    JsonValue,
    LoanRequestInput,
    ResolvesAnnualIncome,
    UserProfile,
)

PROPERTY_AFFORDABILITY_RESULT_SCHEMA_VERSION = "1.0.0"
PROPERTY_AFFORDABILITY_AI_HANDOFF_SCHEMA_VERSION = "1.0.0"

AI_GENERATION_RULES = (
    "Use the supplied calculation values without recalculating or rounding them.",
    "Do not describe UNKNOWN or UNSUPPORTED results as purchase approval.",
    "State material missing inputs and assumptions next to the affected conclusion.",
    "Keep policy source labels attached to regulatory or product claims.",
)


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class PropertyAcquisitionFactsInput(BaseModel):
    """Legal facts that may vary by listing and must not be guessed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_registered_housing: bool | None = None
    is_luxury_home: bool | None = None
    is_national_housing_scale_override: bool | None = None
    registration_and_legal_costs: Decimal | None = Field(default=None, ge=0)
    brokerage_vat_rate_override: Decimal | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_housing_classification(self) -> "PropertyAcquisitionFactsInput":
        if self.is_registered_housing is False and (
            self.is_national_housing_scale_override is True
        ):
            raise ValueError("non-housing property cannot be marked as national housing scale")
        return self


class PropertyAcquisitionProfileInput(BaseModel):
    """Buyer-wide facts plus optional listing-specific acquisition-cost overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    buyer_is_corporation: bool | None = None
    household_home_count_after_purchase: int | None = Field(default=None, gt=0)
    default_property_facts: PropertyAcquisitionFactsInput = Field(
        default_factory=PropertyAcquisitionFactsInput
    )
    listing_overrides: dict[str, PropertyAcquisitionFactsInput] = Field(default_factory=dict)

    @field_validator("listing_overrides")
    @classmethod
    def validate_listing_ids(
        cls,
        values: dict[str, PropertyAcquisitionFactsInput],
    ) -> dict[str, PropertyAcquisitionFactsInput]:
        if any(not listing_id.strip() for listing_id in values):
            raise ValueError("listing override identifiers must not be blank")
        return values

    @model_validator(mode="after")
    def validate_merged_overrides(self) -> "PropertyAcquisitionProfileInput":
        for listing_id in self.listing_overrides:
            self.facts_for(listing_id)
        return self

    def facts_for(self, listing_id: str) -> PropertyAcquisitionFactsInput:
        override = self.listing_overrides.get(listing_id)
        if override is None:
            return self.default_property_facts
        merged = self.default_property_facts.model_dump()
        merged.update(override.model_dump(exclude_none=True))
        return PropertyAcquisitionFactsInput.model_validate(merged)


class PropertyAffordabilitySearchRequest(BaseModel, ResolvesAnnualIncome):
    """Frontend filters and finance facts for a single search-and-evaluate call."""

    model_config = ConfigDict(extra="forbid")

    criteria: PropertySearchCriteria
    profile: UserProfile
    financial_snapshot: FinancialSnapshot
    loan_request: LoanRequestInput | None = None
    acquisition_profile: PropertyAcquisitionProfileInput = Field(
        default_factory=PropertyAcquisitionProfileInput
    )

    @model_validator(mode="after")
    def validate_property_specific_loan_request(self) -> "PropertyAffordabilitySearchRequest":
        if self.loan_request is None:
            return self
        if not self.loan_request.for_house_purchase:
            raise ValueError("property affordability only supports house-purchase loans")
        if self.loan_request.required_amount is not None:
            raise ValueError(
                "loan_request.required_amount must be omitted because it is calculated per listing"
            )
        return self


class PropertyAffordabilityAssessment(BaseModel):
    """Stable summary plus the lossless engine result for one property."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: PropertyCandidate
    verdict: AffordabilityVerdict
    minimum_total_purchase_cost: Decimal = Field(ge=0)
    total_purchase_cost: Decimal | None = Field(default=None, ge=0)
    usable_liquid_assets_before_purchase: Decimal = Field(ge=0)
    required_loan_amount: Decimal | None = Field(default=None, ge=0)
    selected_loan_products: tuple[str, ...] = ()
    loan_funding_amount: Decimal | None = Field(default=None, ge=0)
    funding_gap: Decimal | None = Field(default=None, ge=0)
    monthly_loan_payment: Decimal | None = Field(default=None, ge=0)
    post_purchase_monthly_surplus: Decimal | None = None
    stress_monthly_surplus: Decimal | None = None
    engine_result: dict[str, JsonValue]
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_engine_summary(self) -> "PropertyAffordabilityAssessment":
        if self.engine_result.get("listing_id") != self.candidate.listing_id:
            raise ValueError("engine result listing_id must match the candidate")
        if self.engine_result.get("verdict") != self.verdict.value:
            raise ValueError("engine result verdict must match the assessment")
        if (
            self.total_purchase_cost is not None
            and self.total_purchase_cost < self.minimum_total_purchase_cost
        ):
            raise ValueError("total purchase cost must not be below its known minimum")
        return self


class PropertyAffordabilitySearchResponse(BaseModel):
    """SSOT response consumed by the web UI and downstream report handoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = PROPERTY_AFFORDABILITY_RESULT_SCHEMA_VERSION
    calculated_at: datetime
    search_result: PropertySearchResult
    total_count: int = Field(ge=0)
    assessments: tuple[PropertyAffordabilityAssessment, ...]
    verdict_counts: dict[str, int]
    missing_inputs: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()

    @field_validator("calculated_at")
    @classmethod
    def validate_calculated_at(cls, value: datetime) -> datetime:
        if not _is_timezone_aware(value):
            raise ValueError("calculated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_response_consistency(self) -> "PropertyAffordabilitySearchResponse":
        if self.total_count != len(self.assessments):
            raise ValueError("total_count must equal the number of assessments")
        if self.total_count != self.search_result.total_count:
            raise ValueError("assessment and search result totals must match")
        candidate_ids = tuple(
            candidate.listing_id for candidate in self.search_result.candidates
        )
        assessment_ids = tuple(
            assessment.candidate.listing_id for assessment in self.assessments
        )
        if candidate_ids != assessment_ids:
            raise ValueError("assessment order must match the searched candidates")
        expected_counts: dict[str, int] = {}
        for assessment in self.assessments:
            key = assessment.verdict.value
            expected_counts[key] = expected_counts.get(key, 0) + 1
        if self.verdict_counts != expected_counts:
            raise ValueError("verdict_counts must match the assessments")
        expected_missing = _dedupe(
            [
                item
                for assessment in self.assessments
                for item in assessment.missing_inputs
            ]
        )
        if self.missing_inputs != expected_missing:
            raise ValueError("missing_inputs must aggregate assessment values in order")
        expected_sources = _dedupe(
            [
                item
                for assessment in self.assessments
                for item in assessment.policy_sources
            ]
        )
        if self.policy_sources != expected_sources:
            raise ValueError("policy_sources must aggregate assessment values in order")
        return self

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PropertyAffordabilityAIItem(BaseModel):
    """Only the verified listing and calculation facts needed for narrative output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    listing_id: str = Field(min_length=1)
    property_name: str | None = None
    address_summary: str
    price_krw: Decimal = Field(gt=0)
    nearest_station_walk_minutes: int | None = Field(default=None, ge=0)
    verdict: AffordabilityVerdict
    minimum_total_purchase_cost: Decimal = Field(ge=0)
    total_purchase_cost: Decimal | None = Field(default=None, ge=0)
    usable_liquid_assets_before_purchase: Decimal = Field(ge=0)
    required_loan_amount: Decimal | None = Field(default=None, ge=0)
    selected_loan_products: tuple[str, ...] = ()
    loan_funding_amount: Decimal | None = Field(default=None, ge=0)
    funding_gap: Decimal | None = Field(default=None, ge=0)
    monthly_loan_payment: Decimal | None = Field(default=None, ge=0)
    post_purchase_monthly_surplus: Decimal | None = None
    stress_monthly_surplus: Decimal | None = None
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()


class PropertyAffordabilityAIHandoff(BaseModel):
    """PII-minimized, immutable handoff for the AI report worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = PROPERTY_AFFORDABILITY_AI_HANDOFF_SCHEMA_VERSION
    search_snapshot_id: UUID
    calculated_at: datetime
    data_as_of: datetime
    source: PropertySourceMetadata
    items: tuple[PropertyAffordabilityAIItem, ...]
    missing_inputs: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()
    generation_rules: tuple[str, ...] = AI_GENERATION_RULES

    @field_validator("calculated_at", "data_as_of")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        if not _is_timezone_aware(value):
            raise ValueError("AI handoff timestamps must include a timezone")
        return value


__all__ = [
    "AI_GENERATION_RULES",
    "PROPERTY_AFFORDABILITY_AI_HANDOFF_SCHEMA_VERSION",
    "PROPERTY_AFFORDABILITY_RESULT_SCHEMA_VERSION",
    "PropertyAcquisitionFactsInput",
    "PropertyAcquisitionProfileInput",
    "PropertyAffordabilityAIHandoff",
    "PropertyAffordabilityAIItem",
    "PropertyAffordabilityAssessment",
    "PropertyAffordabilitySearchRequest",
    "PropertyAffordabilitySearchResponse",
]
