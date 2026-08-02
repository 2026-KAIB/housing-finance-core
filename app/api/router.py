from fastapi import APIRouter

from app.api.routes import health, properties, reports, simulations
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(health.router)
# 같은 라우터를 API 접두사 아래에도 건다. 프론트엔드 프록시는 `/api/...`만
# 백엔드로 넘기므로, 루트에만 있으면 웹에서 배포 상태를 확인할 길이 없다.
# 백엔드 포트는 외부에 열지 않으므로 루트 경로는 컨테이너 헬스체크 전용이다.
api_router.include_router(health.router, prefix=settings.api_prefix)
api_router.include_router(
    simulations.router,
    prefix=f"{settings.api_prefix}/simulations",
    tags=["simulations"],
)
api_router.include_router(
    properties.router,
    prefix=f"{settings.api_prefix}/properties",
    tags=["properties"],
)
api_router.include_router(
    reports.router,
    prefix=f"{settings.api_prefix}/reports",
    tags=["reports"],
)
