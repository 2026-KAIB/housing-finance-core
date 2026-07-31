"""Structured property search and affordability endpoints used by the frontend."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.repositories import (
    JsonPropertyListingRepository,
    PropertyDatasetLoadError,
)
from app.rule_engine.product_packs.handoff import ProductCandidate as LoanProductCandidate
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.schemas.property import PropertySearchCriteria, PropertySearchResult
from app.schemas.property_affordability import (
    PropertyAffordabilitySearchRequest,
    PropertyAffordabilitySearchResponse,
)
from app.schemas.property_price import RegionPriceReference
from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)
from app.services.property_affordability_api import (
    evaluate_property_search_affordability,
)
from app.services.property_search import search_properties
from app.services.region_price import (
    RegionNotFound,
    RegionPriceUnavailable,
    load_region_price_reference,
)

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
    """Load candidates without treating provider failure as an empty catalog."""

    try:
        return load_configured_loan_candidates(as_of=calculated_at.date())
    except LoanProductCatalogUnavailable as exc:
        logger.error("failed to load the configured loan-product catalog", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="대출 상품 데이터를 불러올 수 없습니다.",
        ) from exc


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


def get_region_price_reference_loader() -> Callable[[str], RegionPriceReference]:
    """테스트가 DB 없이 갈아끼울 수 있도록 조회 함수를 의존성으로 노출한다."""

    return load_region_price_reference


@router.get("/price-reference", response_model=RegionPriceReference)
def read_region_price_reference(
    sgg_code: Annotated[
        str,
        # 형식만 코드로 막는다. 25개 구 목록의 정본은 DB의 sgg_codes이며,
        # 상수로 복제하면 DB와 어긋날 때 어느 쪽이 맞는지 판단할 근거가 없다.
        Query(pattern=r"^11\d{3}$", description="서울 자치구 시군구 코드"),
    ],
    loader: Annotated[
        Callable[[str], RegionPriceReference],
        Depends(get_region_price_reference_loader),
    ],
) -> RegionPriceReference:
    """자치구 단위 평형대별 시세를 돌려준다(`stat_level='sgg_all'`).

    이 DB에는 판매 중인 매물이 없으므로(`apt_trades`는 체결 이력) 개별 물건이
    아니라 실거래 집계를 돌려준다.
    """

    try:
        return loader(sgg_code)
    except RegionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 시군구 코드를 찾을 수 없습니다.",
        ) from exc
    except RegionPriceUnavailable as exc:
        # 원인은 로그에만 남긴다 — 접속 정보가 예외 메시지를 타고 나가지 않게.
        logger.error("failed to load the configured region-price provider", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="시세 데이터를 불러올 수 없습니다.",
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
