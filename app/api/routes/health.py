from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)

router = APIRouter(tags=["health"])
SEOUL = ZoneInfo("Asia/Seoul")


@router.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready")
def readiness_check() -> dict[str, str | int]:
    """Check the configured product provider used by real calculations."""

    try:
        candidates = load_configured_loan_candidates(
            as_of=datetime.now(tz=SEOUL).date()
        )
    except LoanProductCatalogUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="대출 상품 데이터 공급자가 준비되지 않았습니다.",
        ) from exc
    return {
        "status": "ready",
        "service": settings.app_name,
        "loan_product_provider": settings.loan_product_provider,
        "loan_product_count": len(candidates),
    }
