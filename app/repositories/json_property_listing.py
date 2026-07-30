"""JSON-backed property repository used until the normalized database is ready."""

from pathlib import Path

from pydantic import ValidationError

from app.schemas.property import PropertyListingDataset, PropertySearchCriteria


class PropertyDatasetLoadError(ValueError):
    """Raised when a property snapshot cannot be read or violates its contract."""


class JsonPropertyListingRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_dataset(self) -> PropertyListingDataset:
        try:
            raw_json = self.path.read_text(encoding="utf-8-sig")
            return PropertyListingDataset.model_validate_json(raw_json)
        except (OSError, ValidationError) as exc:
            raise PropertyDatasetLoadError(
                f"failed to load property dataset from {self.path}: {exc}"
            ) from exc

    def search_candidates(
        self,
        criteria: PropertySearchCriteria,
    ) -> PropertyListingDataset:
        """JSON is small enough to load fully; the service applies exact filtering."""

        del criteria
        return self.load_dataset()
