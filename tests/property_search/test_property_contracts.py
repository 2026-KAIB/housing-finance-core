import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.property import (
    PropertyListingDataset,
    PropertyLocation,
    PropertySearchCriteria,
)

_DATASET_PATH = (
    Path(__file__).parents[2] / "sample_data" / "property_listings" / "property_listings.v1.json"
)


def _raw_dataset() -> dict:
    return json.loads(_DATASET_PATH.read_text(encoding="utf-8"))


def test_sample_property_dataset_matches_versioned_contract() -> None:
    dataset = PropertyListingDataset.model_validate(_raw_dataset())
    payload = json.loads(dataset.model_dump_json())

    assert dataset.schema_version == "1.0.0"
    assert len(dataset.listings) == 6
    assert payload["listings"][0]["price_krw"] == "49000000"
    assert payload["listings"][0]["exclusive_area_m2"] == "37.50"
    assert dataset.data_as_of.utcoffset() is not None


def test_dataset_rejects_duplicate_internal_and_source_ids() -> None:
    raw = _raw_dataset()
    raw["listings"].append(dict(raw["listings"][0]))

    with pytest.raises(ValidationError, match="listing_id must be unique"):
        PropertyListingDataset.model_validate(raw)

    raw = _raw_dataset()
    raw["listings"][1]["source_listing_id"] = raw["listings"][0]["source_listing_id"]
    with pytest.raises(ValidationError, match="source_listing_id must be unique"):
        PropertyListingDataset.model_validate(raw)


def test_dataset_rejects_naive_or_reversed_listing_timestamps() -> None:
    raw = _raw_dataset()
    raw["listings"][0]["updated_at"] = "2026-07-29T18:00:00"
    with pytest.raises(ValidationError, match="must include a timezone"):
        PropertyListingDataset.model_validate(raw)

    raw = _raw_dataset()
    raw["listings"][0]["updated_at"] = "2026-07-19T18:00:00+09:00"
    with pytest.raises(ValidationError, match="must not be earlier"):
        PropertyListingDataset.model_validate(raw)

    raw = _raw_dataset()
    raw["listings"][0]["updated_at"] = "2026-07-30T09:00:01+09:00"
    with pytest.raises(ValidationError, match="later than data_as_of"):
        PropertyListingDataset.model_validate(raw)


def test_location_rejects_only_one_coordinate() -> None:
    with pytest.raises(ValidationError, match="both be present"):
        PropertyLocation(latitude="37.48")


@pytest.mark.parametrize(
    "payload,error",
    [
        (
            {"region_codes": ["1162"]},
            "region code must contain 2, 5, or 10 digits",
        ),
        (
            {"region_codes": ["11620", "11620"]},
            "region_codes must not contain duplicates",
        ),
        (
            {"min_price_krw": "50000001", "max_price_krw": "50000000"},
            "min_price_krw must not exceed",
        ),
        (
            {
                "min_exclusive_area_m2": "50",
                "max_exclusive_area_m2": "40",
            },
            "min_exclusive_area_m2 must not exceed",
        ),
    ],
)
def test_search_criteria_rejects_ambiguous_or_reversed_values(
    payload: dict,
    error: str,
) -> None:
    with pytest.raises(ValidationError, match=error):
        PropertySearchCriteria.model_validate(payload)
