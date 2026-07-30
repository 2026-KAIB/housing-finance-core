import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.repositories import JsonPropertyListingRepository
from app.schemas.property import PropertySearchCriteria, PropertySearchSort
from app.services.property_search import search_properties, search_property_dataset

_FIXTURE_DIR = Path(__file__).parents[2] / "sample_data" / "property_listings"
_DATASET_PATH = _FIXTURE_DIR / "property_listings.v1.json"
_CASES_PATH = _FIXTURE_DIR / "property_search_cases.v1.json"
_SEARCH_ID = UUID("00000000-0000-0000-0000-000000000101")
_SEARCHED_AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _repository() -> JsonPropertyListingRepository:
    return JsonPropertyListingRepository(_DATASET_PATH)


def _listing_ids(result) -> list[str]:
    return [candidate.listing_id for candidate in result.candidates]


def test_documented_search_cases_are_executable_contracts() -> None:
    dataset = _repository().load_dataset()
    fixture = json.loads(_CASES_PATH.read_text(encoding="utf-8"))

    for case in fixture["cases"]:
        result = search_property_dataset(
            dataset,
            PropertySearchCriteria.model_validate(case["criteria"]),
            search_snapshot_id=_SEARCH_ID,
            searched_at=_SEARCHED_AT,
        )
        assert _listing_ids(result) == case["expected_listing_ids"], case["case_id"]


def test_price_boundary_is_inclusive_and_inactive_listing_is_excluded() -> None:
    result = search_property_dataset(
        _repository().load_dataset(),
        PropertySearchCriteria(
            region_codes=("11620",),
            max_price_krw="50000000",
        ),
        search_snapshot_id=_SEARCH_ID,
        searched_at=_SEARCHED_AT,
    )

    assert "MOCK-GWANAK-002" in _listing_ids(result)
    assert "MOCK-GWANAK-004" not in _listing_ids(result)


def test_missing_area_or_transit_is_excluded_only_when_that_filter_is_enabled() -> None:
    dataset = _repository().load_dataset()

    no_optional_filter = search_property_dataset(
        dataset,
        PropertySearchCriteria(region_codes=("11620",), max_price_krw="50000000"),
        search_snapshot_id=_SEARCH_ID,
        searched_at=_SEARCHED_AT,
    )
    with_optional_filters = search_property_dataset(
        dataset,
        PropertySearchCriteria(
            region_codes=("11620",),
            max_price_krw="50000000",
            min_exclusive_area_m2="30",
            max_station_walk_minutes=10,
        ),
        search_snapshot_id=_SEARCH_ID,
        searched_at=_SEARCHED_AT,
    )

    assert "MOCK-GWANAK-006" in _listing_ids(no_optional_filter)
    assert "MOCK-GWANAK-006" not in _listing_ids(with_optional_filters)
    assert _listing_ids(with_optional_filters) == ["MOCK-GWANAK-001"]


def test_updated_sort_is_descending_with_unknown_timestamp_last() -> None:
    result = search_property_dataset(
        _repository().load_dataset(),
        PropertySearchCriteria(
            region_codes=("11620",),
            sort=PropertySearchSort.UPDATED_DESC,
        ),
        search_snapshot_id=_SEARCH_ID,
        searched_at=_SEARCHED_AT,
    )

    assert _listing_ids(result) == [
        "MOCK-GWANAK-002",
        "MOCK-GWANAK-001",
        "MOCK-GWANAK-003",
        "MOCK-GWANAK-006",
    ]


def test_repository_service_generates_a_snapshot_without_knowing_storage_type() -> None:
    result = search_properties(
        _repository(),
        PropertySearchCriteria(
            region_codes=("11620",),
            property_types=("VILLA",),
            max_price_krw="50000000",
            max_station_walk_minutes=10,
        ),
        now=lambda: _SEARCHED_AT,
        id_factory=lambda: _SEARCH_ID,
    )

    assert result.search_snapshot_id == _SEARCH_ID
    assert result.searched_at == _SEARCHED_AT
    assert result.source.source_version == "2026-07-30.1"
    assert result.total_count == 1
    assert result.candidates[0].listing_id == "MOCK-GWANAK-001"


def test_search_result_rejects_a_clock_without_timezone() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        search_property_dataset(
            _repository().load_dataset(),
            PropertySearchCriteria(),
            search_snapshot_id=_SEARCH_ID,
            searched_at=datetime(2026, 7, 30, 12, 0),
        )
