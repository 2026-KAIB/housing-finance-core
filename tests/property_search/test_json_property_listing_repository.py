from pathlib import Path

import pytest

from app.repositories import (
    JsonPropertyListingRepository,
    PropertyDatasetLoadError,
)

_DATASET_PATH = (
    Path(__file__).parents[2] / "sample_data" / "property_listings" / "property_listings.v1.json"
)


def test_json_repository_loads_a_validated_snapshot() -> None:
    repository = JsonPropertyListingRepository(_DATASET_PATH)

    dataset = repository.load_dataset()

    assert dataset.source.source_type == "MOCK"
    assert dataset.source.source_name == "team-mock-property-data"
    assert dataset.listings[0].listing_id == "MOCK-GWANAK-001"


def test_json_repository_wraps_missing_and_invalid_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(PropertyDatasetLoadError, match="missing.json"):
        JsonPropertyListingRepository(missing).load_dataset()

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version":"9.9.9"}', encoding="utf-8")
    with pytest.raises(PropertyDatasetLoadError, match="invalid.json"):
        JsonPropertyListingRepository(invalid).load_dataset()
