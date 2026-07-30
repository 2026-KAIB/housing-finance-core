"""Structured property search endpoint used by the frontend filters."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.repositories import JsonPropertyListingRepository, PropertyDatasetLoadError
from app.schemas.property import PropertySearchCriteria, PropertySearchResult
from app.services.property_search import search_properties

router = APIRouter()
SEOUL = ZoneInfo("Asia/Seoul")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _property_dataset_path() -> Path:
    configured = settings.property_listing_json_path
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


@router.post("/search", response_model=PropertySearchResult)
def search_property_listings(criteria: PropertySearchCriteria) -> PropertySearchResult:
    """Search the configured snapshot without coupling filters to its storage type."""

    repository = JsonPropertyListingRepository(_property_dataset_path())
    try:
        return search_properties(
            repository,
            criteria,
            now=lambda: datetime.now(SEOUL),
        )
    except PropertyDatasetLoadError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="매물 데이터 스냅샷을 불러올 수 없습니다.",
        ) from exc
