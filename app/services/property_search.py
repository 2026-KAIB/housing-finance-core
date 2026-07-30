"""Deterministic structured property search independent of the storage provider."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from app.repositories.property_listing import PropertyListingRepository
from app.schemas.property import (
    ListingStatus,
    PropertyCandidate,
    PropertyListingDataset,
    PropertySearchCriteria,
    PropertySearchResult,
    PropertySearchSort,
)


def _matches(candidate: PropertyCandidate, criteria: PropertySearchCriteria) -> bool:
    if candidate.status is not ListingStatus.ACTIVE:
        return False
    if candidate.transaction_type is not criteria.transaction_type:
        return False
    if criteria.region_codes and not any(
        candidate.region.matches(code) for code in criteria.region_codes
    ):
        return False
    if criteria.property_types and candidate.property_type not in criteria.property_types:
        return False
    if criteria.min_price_krw is not None and candidate.price_krw < criteria.min_price_krw:
        return False
    if criteria.max_price_krw is not None and candidate.price_krw > criteria.max_price_krw:
        return False
    if criteria.min_exclusive_area_m2 is not None and (
        candidate.exclusive_area_m2 is None
        or candidate.exclusive_area_m2 < criteria.min_exclusive_area_m2
    ):
        return False
    if criteria.max_exclusive_area_m2 is not None and (
        candidate.exclusive_area_m2 is None
        or candidate.exclusive_area_m2 > criteria.max_exclusive_area_m2
    ):
        return False
    if criteria.max_station_walk_minutes is not None and (
        candidate.nearest_walk_minutes is None
        or candidate.nearest_walk_minutes > criteria.max_station_walk_minutes
    ):
        return False
    return True


def _updated_desc_key(candidate: PropertyCandidate) -> tuple[bool, Decimal, str]:
    if candidate.updated_at is None:
        return (True, Decimal(0), candidate.listing_id)
    timestamp = Decimal(str(candidate.updated_at.timestamp()))
    return (False, -timestamp, candidate.listing_id)


def _sort_candidates(
    candidates: list[PropertyCandidate],
    sort: PropertySearchSort,
) -> tuple[PropertyCandidate, ...]:
    if sort is PropertySearchSort.UPDATED_DESC:
        return tuple(sorted(candidates, key=_updated_desc_key))
    if sort is PropertySearchSort.STATION_WALK_ASC:
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    candidate.nearest_walk_minutes is None,
                    candidate.nearest_walk_minutes or 0,
                    candidate.price_krw,
                    candidate.listing_id,
                ),
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (candidate.price_krw, candidate.listing_id),
        )
    )


def search_property_dataset(
    dataset: PropertyListingDataset,
    criteria: PropertySearchCriteria,
    *,
    search_snapshot_id: UUID,
    searched_at: datetime,
) -> PropertySearchResult:
    """Filter one validated snapshot; no I/O or financial feasibility is performed."""

    candidates = [candidate for candidate in dataset.listings if _matches(candidate, criteria)]
    sorted_candidates = _sort_candidates(candidates, criteria.sort)
    return PropertySearchResult(
        search_snapshot_id=search_snapshot_id,
        searched_at=searched_at,
        data_as_of=dataset.data_as_of,
        source=dataset.source,
        criteria=criteria,
        total_count=len(sorted_candidates),
        candidates=sorted_candidates,
    )


def search_properties(
    repository: PropertyListingRepository,
    criteria: PropertySearchCriteria,
    *,
    now: Callable[[], datetime],
    id_factory: Callable[[], UUID] = uuid4,
) -> PropertySearchResult:
    """Load a provider snapshot and run the same search for JSON or a future DB."""

    return search_property_dataset(
        repository.search_candidates(criteria),
        criteria,
        search_snapshot_id=id_factory(),
        searched_at=now(),
    )


__all__ = ["search_properties", "search_property_dataset"]
