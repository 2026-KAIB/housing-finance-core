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
from app.schemas.property_trade import RegionTradePage, TradeSort
from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)
from app.services.property_affordability_api import (
    evaluate_property_search_affordability,
)
from app.services.property_search import search_properties
from app.services.region_trade import (
    RegionNotFound,
    RegionTradesUnavailable,
    load_region_trades,
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


RegionTradeLoader = Callable[..., RegionTradePage]


def get_region_trades_loader() -> RegionTradeLoader:
    """테스트가 DB 없이 갈아끼울 수 있도록 조회 함수를 의존성으로 노출한다."""

    return load_region_trades


@router.get("/trades", response_model=RegionTradePage)
def read_region_trades(
    sgg_code: Annotated[
        str,
        # 형식만 코드로 막는다. 25개 구 목록의 정본은 DB의 sgg_codes이며,
        # 상수로 복제하면 DB와 어긋날 때 어느 쪽이 맞는지 판단할 근거가 없다.
        Query(pattern=r"^11\d{3}$", description="서울 자치구 시군구 코드"),
    ],
    loader: Annotated[RegionTradeLoader, Depends(get_region_trades_loader)],
    sort: Annotated[TradeSort, Query(description="정렬 기준")] = TradeSort.AREA_ASC,
    page: Annotated[int, Query(ge=1, description="1부터 시작")] = 1,
    page_size: Annotated[int, Query(ge=1, le=50, description="한 페이지 행 수")] = 5,
) -> RegionTradePage:
    """자치구의 실거래를 정렬·페이징해 돌려준다.

    이 DB에는 판매 중인 매물이 없으므로(`apt_trades`는 체결 이력) 돌려주는 것은
    이미 끝난 거래다. 집계가 아니라 개별 거래인 이유는 같은 아파트·같은 면적도
    층마다 가격이 다르기 때문이다.
    """

    try:
        return loader(sgg_code, sort=sort, page=page, page_size=page_size)
    except RegionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 시군구 코드를 찾을 수 없습니다.",
        ) from exc
    except RegionTradesUnavailable as exc:
        # 원인은 로그에만 남긴다 — 접속 정보가 예외 메시지를 타고 나가지 않게.
        logger.error("failed to load the configured region-trade provider", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="실거래 데이터를 불러올 수 없습니다.",
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
