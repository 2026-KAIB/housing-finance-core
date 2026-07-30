"""Versioned contracts for property listing data and structured searches."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROPERTY_DATASET_SCHEMA_VERSION = "1.0.0"
PROPERTY_SEARCH_RESULT_SCHEMA_VERSION = "1.0.0"
_REGION_CODE_LENGTHS = {2, 5, 10}


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class ListingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SOLD = "SOLD"
    DELETED = "DELETED"


class TransactionType(StrEnum):
    """Version 1 is purchase-only; rent-specific prices require a new contract."""

    SALE = "SALE"


class PropertyType(StrEnum):
    APARTMENT = "APARTMENT"
    VILLA = "VILLA"
    OFFICETEL = "OFFICETEL"
    HOUSE = "HOUSE"


class PropertyDataSourceType(StrEnum):
    MOCK = "MOCK"
    FILE = "FILE"
    PUBLIC_API = "PUBLIC_API"
    PARTNER_API = "PARTNER_API"
    DATABASE = "DATABASE"


class PropertySearchSort(StrEnum):
    PRICE_ASC = "PRICE_ASC"
    UPDATED_DESC = "UPDATED_DESC"
    STATION_WALK_ASC = "STATION_WALK_ASC"


class PropertySourceMetadata(BaseModel):
    """Provenance of one property listing dataset snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: PropertyDataSourceType
    source_name: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_url: str | None = None
    license_note: str | None = None


class PropertyRegion(BaseModel):
    """Administrative codes used for exact, language-independent filtering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sido_code: str = Field(pattern=r"^\d{2}$")
    sigungu_code: str = Field(pattern=r"^\d{5}$")
    legal_dong_code: str | None = Field(default=None, pattern=r"^\d{10}$")
    legal_dong_name: str | None = None
    address_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_code_hierarchy(self) -> "PropertyRegion":
        if not self.sigungu_code.startswith(self.sido_code):
            raise ValueError("sigungu_code must start with sido_code")
        if self.legal_dong_code is not None and not self.legal_dong_code.startswith(
            self.sigungu_code
        ):
            raise ValueError("legal_dong_code must start with sigungu_code")
        return self

    def matches(self, region_code: str) -> bool:
        return region_code in {
            self.sido_code,
            self.sigungu_code,
            self.legal_dong_code,
        }


class PropertyLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> "PropertyLocation":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be present or both be null")
        return self


class TransitAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    station_id: str | None = None
    station_name: str = Field(min_length=1)
    line_names: tuple[str, ...] = ()
    walk_minutes: int = Field(ge=0)
    distance_m: int | None = Field(default=None, ge=0)
    calculation_method: str = Field(min_length=1)


class PropertyCandidate(BaseModel):
    """Provider-independent listing shape consumed by the search and finance engines."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    listing_id: str = Field(min_length=1)
    source_listing_id: str = Field(min_length=1)
    status: ListingStatus
    transaction_type: TransactionType
    property_type: PropertyType
    property_name: str | None = None
    region: PropertyRegion
    price_krw: Decimal = Field(gt=0)
    exclusive_area_m2: Decimal | None = Field(default=None, gt=0)
    floor: int | None = None
    location: PropertyLocation = Field(default_factory=PropertyLocation)
    transit_access: tuple[TransitAccess, ...] = ()
    listed_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("listed_at", "updated_at")
    @classmethod
    def validate_timestamp_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and not _is_timezone_aware(value):
            raise ValueError("listing timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "PropertyCandidate":
        if (
            self.listed_at is not None
            and self.updated_at is not None
            and self.updated_at < self.listed_at
        ):
            raise ValueError("updated_at must not be earlier than listed_at")
        return self

    @property
    def nearest_walk_minutes(self) -> int | None:
        if not self.transit_access:
            return None
        return min(access.walk_minutes for access in self.transit_access)


class PropertyListingDataset(BaseModel):
    """A replaceable JSON/DB snapshot with explicit version and provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = PROPERTY_DATASET_SCHEMA_VERSION
    data_as_of: datetime
    source: PropertySourceMetadata
    listings: tuple[PropertyCandidate, ...]

    @field_validator("data_as_of")
    @classmethod
    def validate_data_as_of_timezone(cls, value: datetime) -> datetime:
        if not _is_timezone_aware(value):
            raise ValueError("data_as_of must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_unique_listing_ids(self) -> "PropertyListingDataset":
        listing_ids = [listing.listing_id for listing in self.listings]
        source_listing_ids = [listing.source_listing_id for listing in self.listings]
        if len(listing_ids) != len(set(listing_ids)):
            raise ValueError("listing_id must be unique within a dataset")
        if len(source_listing_ids) != len(set(source_listing_ids)):
            raise ValueError("source_listing_id must be unique within a single-source dataset")
        if any(
            timestamp is not None and timestamp > self.data_as_of
            for listing in self.listings
            for timestamp in (listing.listed_at, listing.updated_at)
        ):
            raise ValueError("listing timestamps must not be later than data_as_of")
        return self


class PropertySearchCriteria(BaseModel):
    """Structured form values that can later also be produced by an NLP parser."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    region_codes: tuple[str, ...] = ()
    transaction_type: TransactionType = TransactionType.SALE
    property_types: tuple[PropertyType, ...] = ()
    min_price_krw: Decimal | None = Field(default=None, ge=0)
    max_price_krw: Decimal | None = Field(default=None, gt=0)
    min_exclusive_area_m2: Decimal | None = Field(default=None, gt=0)
    max_exclusive_area_m2: Decimal | None = Field(default=None, gt=0)
    max_station_walk_minutes: int | None = Field(default=None, ge=0)
    sort: PropertySearchSort = PropertySearchSort.PRICE_ASC

    @field_validator("region_codes")
    @classmethod
    def validate_region_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("region_codes must not contain duplicates")
        for value in values:
            if not value.isdigit() or len(value) not in _REGION_CODE_LENGTHS:
                raise ValueError("region code must contain 2, 5, or 10 digits")
        return values

    @field_validator("property_types")
    @classmethod
    def validate_property_types(
        cls,
        values: tuple[PropertyType, ...],
    ) -> tuple[PropertyType, ...]:
        if len(values) != len(set(values)):
            raise ValueError("property_types must not contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_ranges(self) -> "PropertySearchCriteria":
        if (
            self.min_price_krw is not None
            and self.max_price_krw is not None
            and self.min_price_krw > self.max_price_krw
        ):
            raise ValueError("min_price_krw must not exceed max_price_krw")
        if (
            self.min_exclusive_area_m2 is not None
            and self.max_exclusive_area_m2 is not None
            and self.min_exclusive_area_m2 > self.max_exclusive_area_m2
        ):
            raise ValueError("min_exclusive_area_m2 must not exceed max_exclusive_area_m2")
        return self


class PropertySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = PROPERTY_SEARCH_RESULT_SCHEMA_VERSION
    search_snapshot_id: UUID
    searched_at: datetime
    data_as_of: datetime
    source: PropertySourceMetadata
    criteria: PropertySearchCriteria
    total_count: int = Field(ge=0)
    candidates: tuple[PropertyCandidate, ...]

    @field_validator("searched_at", "data_as_of")
    @classmethod
    def validate_result_timestamp_timezone(cls, value: datetime) -> datetime:
        if not _is_timezone_aware(value):
            raise ValueError("search result timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_total_count(self) -> "PropertySearchResult":
        if self.total_count != len(self.candidates):
            raise ValueError("total_count must equal the number of candidates")
        if self.data_as_of > self.searched_at:
            raise ValueError("data_as_of must not be later than searched_at")
        return self
