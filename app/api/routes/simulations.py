from fastapi import APIRouter, HTTPException, status

from app.schemas.simulation import SimulationInput, SimulationResult

router = APIRouter()


@router.post("", response_model=SimulationResult)
def create_simulation(payload: SimulationInput) -> SimulationResult:
    """공용 계약을 먼저 고정하기 위한 임시 엔드포인트입니다."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            "Simulation engine is not connected yet: "
            f"target={payload.housing_goal.resolved_target_amount}"
        ),
    )
