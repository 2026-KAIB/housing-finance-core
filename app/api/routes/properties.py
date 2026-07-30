"""Structured property search and affordability endpoints used by the frontend."""

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.repositories import (
    JsonPropertyListingRepository,
    LoanProductSnapshotLoadError,
    PropertyDatasetLoadError,
)
from app.rule_engine.product_packs.handoff import ProductCandidate as LoanProductCandidate
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.schemas.property import PropertySearchCriteria, PropertySearchResult
from app.schemas.property_affordability import (
    PropertyAffordabilitySearchRequest,
    PropertyAffordabilitySearchResponse,
)
from app.services.loan_product_catalog import load_configured_loan_candidates
from app.services.property_affordability_api import (
    evaluate_property_search_affordability,
)
from app.services.property_search import search_properties

router = APIRouter()
logger = logging.getLogger(__name__)
SEOUL = ZoneInfo("Asia/Seoul")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _property_dataset_path() -> Path:
    configured = settings.property_listing_json_path
    return configured if configured.is_absolute() else PROJECT_ROOT / configured


def get_property_repository() -> JsonPropertyListingRepository:
    """Dependency boundary that can later be replaced by the normalized DB adapter."""

    return JsonPropertyListingRepository(_property_dataset_path())


def get_property_calculated_at() -> datetime:
    """Use the Korean policy date around the UTC/KST day boundary."""

    return datetime.now(tz=SEOUL)


def get_property_loan_candidates(
    calculated_at: Annotated[datetime, Depends(get_property_calculated_at)],
) -> Sequence[LoanProductCandidate]:
    """Load the DB export; an invalid snapshot remains an explicit UNKNOWN."""

    try:
        return load_configured_loan_candidates(as_of=calculated_at.date())
    except LoanProductSnapshotLoadError:
        logger.warning("failed to load configured loan-product snapshot", exc_info=True)
        return ()


def get_property_loan_rule_registry() -> ProductRulePackRegistry | None:
    return None


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


@router.post("/affordability", response_model=PropertyAffordabilitySearchResponse)
def evaluate_property_listings(
    payload: PropertyAffordabilitySearchRequest,
    repository: Annotated[
        JsonPropertyListingRepository,
        Depends(get_property_repository),
    ],
    loan_candidates: Annotated[
        Sequence[LoanProductCandidate],
        Depends(get_property_loan_candidates),
    ],
    registry: Annotated[
        ProductRulePackRegistry | None,
        Depends(get_property_loan_rule_registry),
    ],
    calculated_at: Annotated[datetime, Depends(get_property_calculated_at)],
) -> PropertyAffordabilitySearchResponse:
    """Search listings and evaluate each one against the same financial snapshot."""

    try:
        return evaluate_property_search_affordability(
            payload,
            repository,
            calculated_at=calculated_at,
            loan_candidates=loan_candidates,
            registry=registry,
        )
    except PropertyDatasetLoadError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="매물 데이터 스냅샷을 불러올 수 없습니다.",
        ) from exc
