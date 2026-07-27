"""포트폴리오 최종 배분액을 상품정책 Rule Pack으로 재검증하는 경계 어댑터.

목적:
    최초 상품평가 때 통과한 납입액과 포트폴리오가 결정한 최종 납입액이 달라져도
    상품별 최소·최대·조건부 금액 규칙이 계속 유효한지 보장한다.
기능:
    선택된 예금에는 ``deposit_amount``, 적금에는 ``monthly_payment_amount``를
    최종 배분액으로 교체해 기존 ProductCandidate와 동일 기준일의 Rule Pack을
    재실행하고 전체 PASS/FAIL/UNKNOWN 상태와 사유를 반환한다.
근거:
    공식 설계안 §11.1은 가입·납입 조건을 통과한 상품만 점수화하도록 하고,
    §12.1은 상품별 납입한도 충족을 포트폴리오 필수 제약으로 둔다. 특히 현재
    상품 Pack에는 초회 여부에 따라 최소금액이 달라지는 조건도 있어 단순 min/max
    데이터만으로 최종 안전성을 단정하지 않는다.

이 파일은 정책을 수정하거나 배분을 다시 계산하지 않는다. 정책 검증 실패 시
호출 서비스가 해당 후보를 제외해 포트폴리오를 다시 계산해야 한다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.engines.savings.models import SavingsProductKind
from app.engines.savings.portfolio_models import (
    SavingsPortfolioResult,
    SavingsPortfolioStatus,
)
from app.rule_engine.product_packs.handoff import (
    ProductEngineHandoff,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import EvaluationStatus
from app.rule_engine.product_packs.registry import (
    DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
    ProductRulePackRegistry,
)


@dataclass(frozen=True)
class PortfolioAllocationPolicyDecision:
    candidate_id: str
    product_name: str
    status: EvaluationStatus
    pack_version: str | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SavingsPortfolioPolicyValidation:
    status: EvaluationStatus
    decisions: tuple[PortfolioAllocationPolicyDecision, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        return self.status is EvaluationStatus.PASS


def _reasons(handoff: ProductEngineHandoff) -> tuple[str, ...]:
    return tuple(
        reason
        for decision in handoff.rule_result.decisions
        if decision.status is not EvaluationStatus.PASS
        for reason in decision.reasons
    )


def revalidate_savings_portfolio_policy(
    portfolio: SavingsPortfolioResult,
    *,
    handoffs_by_candidate_id: Mapping[str, ProductEngineHandoff],
    registry: ProductRulePackRegistry = DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
) -> SavingsPortfolioPolicyValidation:
    """최종 배분액을 같은 상품·사용자 사실·기준일의 Rule Pack으로 재검증한다."""

    if not portfolio.allocations:
        if portfolio.status is SavingsPortfolioStatus.NO_ALLOCATION_REQUIRED:
            return SavingsPortfolioPolicyValidation(
                status=EvaluationStatus.PASS,
                decisions=(),
            )
        reason = "정책을 재검증할 포트폴리오 배분 결과가 없습니다."
        return SavingsPortfolioPolicyValidation(
            status=EvaluationStatus.UNKNOWN,
            decisions=(),
            reasons=(reason,),
        )

    decisions: list[PortfolioAllocationPolicyDecision] = []
    for allocation in portfolio.allocations:
        original_handoff = handoffs_by_candidate_id.get(allocation.candidate_id)
        if original_handoff is None:
            decisions.append(
                PortfolioAllocationPolicyDecision(
                    candidate_id=allocation.candidate_id,
                    product_name=allocation.product_name,
                    status=EvaluationStatus.UNKNOWN,
                    reasons=("원본 ProductEngineHandoff가 없어 재검증할 수 없습니다.",),
                )
            )
            continue

        amount_field = (
            "deposit_amount"
            if allocation.product_kind is SavingsProductKind.TERM_DEPOSIT
            else "monthly_payment_amount"
        )
        final_facts = dict(original_handoff.user_facts)
        final_facts[amount_field] = allocation.allocation_amount
        routing = route_product_candidates(
            [original_handoff.product],
            user_facts=final_facts,
            as_of=original_handoff.rule_result.as_of,
            registry=registry,
        )
        revalidated = routing.all_results[0]
        decisions.append(
            PortfolioAllocationPolicyDecision(
                candidate_id=allocation.candidate_id,
                product_name=allocation.product_name,
                status=revalidated.status,
                pack_version=revalidated.rule_result.pack_version,
                reasons=_reasons(revalidated),
            )
        )

    statuses = {decision.status for decision in decisions}
    if EvaluationStatus.FAIL in statuses:
        status = EvaluationStatus.FAIL
    elif EvaluationStatus.UNKNOWN in statuses:
        status = EvaluationStatus.UNKNOWN
    else:
        status = EvaluationStatus.PASS
    reasons = tuple(
        reason
        for decision in decisions
        if decision.status is not EvaluationStatus.PASS
        for reason in decision.reasons
    )
    return SavingsPortfolioPolicyValidation(
        status=status,
        decisions=tuple(decisions),
        reasons=reasons,
    )
