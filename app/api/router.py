from fastapi import APIRouter

from app.api.routes import health, simulations
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(
    simulations.router,
    prefix=f"{settings.api_prefix}/simulations",
    tags=["simulations"],
)

