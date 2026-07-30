"""Port implemented by JSON now and by a database repository later."""

from typing import Protocol

from app.schemas.property import PropertyListingDataset, PropertySearchCriteria


class PropertyListingRepository(Protocol):
    def search_candidates(
        self,
        criteria: PropertySearchCriteria,
    ) -> PropertyListingDataset:
        """Return a validated snapshot, optionally prefiltered by the provider."""
