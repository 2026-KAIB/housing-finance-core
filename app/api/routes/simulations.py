from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status

from app.schemas.simulation import SimulationInput, SimulationResult
from app.services.cashflow_diagnosis import diagnose_cashflow
from app.services.simulation_result import build_simulation_result

router = APIRouter()
SEOUL = ZoneInfo("Asia/Seoul")


@router.post("", response_model=SimulationResult)
def create_simulation(payload: SimulationInput) -> SimulationResult:
    """현재 연결된 엔진을 실행하고 단일 시뮬레이션 결과로 조립한다."""

    calculated_at = datetime.now(SEOUL)
    as_of = calculated_at.date()
    try:
        cashflow_result = diagnose_cashflow(payload, as_of=as_of)
        return build_simulation_result(
            payload,
            simulation_id=uuid4(),
            as_of=as_of,
            calculated_at=calculated_at,
            cashflow_result=cashflow_result,
            warnings=(
                "현재 API는 현금흐름·비상자금 엔진만 연결되어 있으며 "
                "다른 계산 구간은 NOT_RUN입니다.",
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
