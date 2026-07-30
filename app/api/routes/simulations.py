"""``/simulations`` HTTP 경계.

계산 순서는 이 파일이 알지 않는다 —
``app/services/simulation_orchestrator.run_simulation()`` 하나만 부른다.

시간·난수 같은 부작용은 경계 모듈로 격리한다는 규약에 따라 ``as_of``와
``simulation_id``를 여기서 만들고, 테스트가 고정할 수 있도록 의존성으로 노출한다.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends

from app.repositories import LoanProductSnapshotLoadError
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.schemas.simulation import SimulationInput, SimulationResult
from app.services.loan_product_catalog import load_configured_loan_candidates
from app.services.simulation_orchestrator import run_simulation

router = APIRouter()
logger = logging.getLogger(__name__)


def get_calculated_at() -> datetime:
    """계산 시각. 테스트가 고정할 수 있도록 의존성으로 분리한다."""

    return datetime.now(tz=UTC)


def get_loan_candidates(
    calculated_at: Annotated[datetime, Depends(get_calculated_at)],
) -> Sequence[ProductCandidate]:
    """계산에 넣을 대출 상품 후보.

    직접 DB 포트가 닫힌 동안 검증된 DBeaver JSON 스냅샷을 사용한다. 파일을
    읽지 못하거나 계약이 깨졌으면 빈 목록을 반환해 기존 UNKNOWN 계약을 유지한다.
    """
    try:
        return load_configured_loan_candidates(as_of=calculated_at.date())
    except LoanProductSnapshotLoadError:
        logger.warning("failed to load configured loan-product snapshot", exc_info=True)
        return ()


def get_loan_rule_registry() -> ProductRulePackRegistry | None:
    """자격판정에 쓸 Rule Pack 레지스트리.

    ``None``이면 기본 레지스트리(실제 상품 팩 전체)를 쓴다. 상품 후보와 마찬가지로
    협력자이므로 의존성으로 노출해 테스트가 교체할 수 있게 한다.
    """
    return None


def get_simulation_id() -> UUID:
    return uuid4()


@router.post("", response_model=SimulationResult)
def create_simulation(
    payload: SimulationInput,
    loan_candidates: Annotated[Sequence[ProductCandidate], Depends(get_loan_candidates)],
    registry: Annotated[ProductRulePackRegistry | None, Depends(get_loan_rule_registry)],
    calculated_at: Annotated[datetime, Depends(get_calculated_at)],
    simulation_id: Annotated[UUID, Depends(get_simulation_id)],
) -> SimulationResult:
    """입력 하나를 실행 가능한 구간까지 계산해 단일 JSON으로 돌려준다.

    확정하지 못한 구간은 오류가 아니라 ``NOT_RUN`` + 결측 사유로 응답한다.
    임의 숫자로 채우는 것보다 "무엇을 알려주면 계산되는지"를 돌려주는 쪽이
    맞기 때문이다(§19).
    """
    return run_simulation(
        payload,
        simulation_id=simulation_id,
        as_of=calculated_at.date(),
        calculated_at=calculated_at,
        loan_candidates=loan_candidates,
        registry=registry,
    )
