from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from app.rule_engine.product_packs.engine import evaluate_product
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductEvaluationResult,
)
from app.rule_engine.product_packs.registry import (
    DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
    ProductRulePackRegistry,
)

# 이 모듈은 Rule Pack 판정 전후에도 상품 기본정보와 optionList를 잃지 않게 보존한다.
# Rule Pack은 기존처럼 가입 필수조건만 평가하며 친구가 만든 Pack 파일은 수정하지 않는다.
# PASS 상품은 forwardable, FAIL 상품은 rejected, UNKNOWN 상품은 needs_review로 분리한다.
# 다음 예적금·대출 엔진은 forwardable의 상품·옵션·사용자 정보만 받아 계산을 계속한다.


@dataclass(frozen=True)
class ProductCandidate:
    """Rule Pack에 넣기 전 상위 서비스가 보유한 상품 원본 데이터."""

    product_name: str
    base_data: Mapping[str, object] = field(default_factory=dict)
    option_list: tuple[Mapping[str, object], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.product_name.strip():
            raise ValueError("product_name은 비어 있을 수 없습니다.")


@dataclass(frozen=True)
class ProductEngineHandoff:
    """다음 계산 엔진으로 전달할 상품·사용자·판정 결과 묶음."""

    product: ProductCandidate
    user_facts: Mapping[str, object]
    rule_result: ProductEvaluationResult

    @property
    def status(self) -> EvaluationStatus:
        return self.rule_result.status


@dataclass(frozen=True)
class ProductRoutingResult:
    """상품 후보를 가입 필수조건 판정 결과에 따라 분류한 결과."""

    forwardable: tuple[ProductEngineHandoff, ...]
    rejected: tuple[ProductEngineHandoff, ...]
    needs_review: tuple[ProductEngineHandoff, ...]

    @property
    def all_results(self) -> tuple[ProductEngineHandoff, ...]:
        return (*self.forwardable, *self.rejected, *self.needs_review)


def route_product_candidates(
    candidates: Sequence[ProductCandidate],
    *,
    user_facts: Mapping[str, object],
    as_of: date,
    registry: ProductRulePackRegistry = DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
) -> ProductRoutingResult:
    """상품 후보를 판정하고 원본 데이터와 함께 다음 단계별로 분류한다."""

    evaluated = tuple(
        _evaluate_candidate(
            candidate,
            user_facts=user_facts,
            as_of=as_of,
            registry=registry,
        )
        for candidate in candidates
    )
    return ProductRoutingResult(
        forwardable=tuple(
            handoff
            for handoff in evaluated
            if handoff.status is EvaluationStatus.PASS
        ),
        rejected=tuple(
            handoff
            for handoff in evaluated
            if handoff.status is EvaluationStatus.FAIL
        ),
        needs_review=tuple(
            handoff
            for handoff in evaluated
            if handoff.status is EvaluationStatus.UNKNOWN
        ),
    )


def _evaluate_candidate(
    candidate: ProductCandidate,
    *,
    user_facts: Mapping[str, object],
    as_of: date,
    registry: ProductRulePackRegistry,
) -> ProductEngineHandoff:
    rule_result = evaluate_product(
        ProductEvaluationRequest(
            product_name=candidate.product_name,
            as_of=as_of,
            facts=user_facts,
        ),
        registry,
    )
    return ProductEngineHandoff(
        product=candidate,
        user_facts=user_facts,
        rule_result=rule_result,
    )
