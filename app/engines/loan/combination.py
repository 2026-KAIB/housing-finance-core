"""여러 대출을 동시에 실행하는 조합안을 결정론적으로 탐색하고 §14로 점수화한다.

핵심 규약 — **공유 예산은 한 번만 쓴다.**
    DSR·구매 후 현금흐름은 차주 한 명당 하나, LTV는 담보주택 하나당 하나다. 다리를
    채울 때마다 그 예산에서 실제로 깎고, 남은 예산을 다리의 상환 계수로 나눠 넣을
    수 있는 최대 원금을 구한다. 예·적금 포트폴리오가 예금자보호 한도를 다루는 방식과
    같은 연산이다(`engines/savings/portfolio.py`의 `_institution_capacity`).

    개별 다리의 최대 한도를 더하면 이 예산을 다리 수만큼 중복 사용한다. 그것이 이
    저장소가 반복해서 고쳐 온 "모르는 것/공유하는 것을 느슨한 쪽으로 뭉개는" 실패의
    조합 버전이다.

왜 탐색이 성립하는가:
    PMT가 원금에 선형이므로(PMT = L × c) 모든 제약이 배분액의 선형 부등식이다.
    계수가 고정된 구간에서는 남은 예산 ÷ 계수가 곧 배분 상한이고, 반복 채우기의
    결과는 항상 실제 실행 가능한 조합이다(과대평가가 없다).

유일한 비선형 — 신용대출 스트레스 문턱:
    가산금리가 잔액 문턱을 넘을 때만 붙으므로 DSR 제약이 배분액에 대해 꺾인다.
    그래서 구간을 둘로 나눠(`CreditStressRegime`) 각 구간에서 선형으로 풀고,
    **전제가 성립하는 해만** 채택한다. 문턱 위 심사금리를 모르면 그 구간을 계산하지
    않고 결측으로 남긴다 — 문턱 아래 금리로 계산하면 가산금리가 빠져 과대평가된다.

무엇을 주장하지 않는가:
    반환하는 상위 조합은 **열거한 후보 집합 안에서의 순위**다. 전역 최적이라고
    주장하지 않는다. 채우는 순서를 여러 개 시도해 후보를 만들며, 순서마다 다른
    제약이 먼저 묶이기 때문이다. §18의 민감도 분석은 이 위에서 별도로 한다.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal
from itertools import combinations
from typing import Protocol

from app.engines.loan.combination_models import (
    DEFAULT_COMBINATION_POLICY,
    CombinationScoreComponents,
    CombinationStatus,
    CreditStressRegime,
    ExcludedCombination,
    LoanCombinationBudget,
    LoanCombinationPlan,
    LoanCombinationPolicy,
    LoanCombinationResult,
    LoanLegAllocation,
    LoanLegCandidate,
    LoanLegKind,
)
from app.engines.loan.formulas import dsr, pmt
from app.engines.recommendation.models import RecommendationPolicy, ScoreStatus

# 채우는 순서. 순서마다 먼저 묶이는 제약이 달라 서로 다른 조합안이 나오므로,
# 하나만 쓰지 않고 전부 후보로 만든다.
#
#   assessment_cost  심사 상환 계수가 낮은 다리부터 — DSR이 병목일 때 총액이 커진다
#   actual_cost      실제 상환 계수가 낮은 다리부터 — 현금흐름이 병목일 때 유리하다
#   flexibility      상환유연성이 높은 다리부터 — 중도상환 여지를 우선한다
_FILL_ORDERS = ("assessment_cost", "actual_cost", "flexibility")

class GateVerdict(Protocol):
    """검수표 판정 결과의 최소 형태.

    구조만 요구해 이 순수 계산 계층이 `data_pipeline`을 import하지 않게 한다 —
    예·적금 엔진이 예금자보호 한도표를 모르는 것과 같은 층 분리다.
    """

    @property
    def is_executable(self) -> bool: ...

    @property
    def blocking_pairs(self) -> tuple[tuple[tuple[str, str], str], ...]: ...

    @property
    def unknown_pairs(self) -> tuple[tuple[str, str], ...]: ...

    @property
    def sources(self) -> tuple[str, ...]: ...


class CombinationGate(Protocol):
    """상품명 목록을 받아 동시 실행 가능 여부를 답하는 함수."""

    def __call__(self, product_names: Sequence[str]) -> GateVerdict: ...


_CONSTRAINT_LABELS = {
    "dsr": "DSR 예산",
    "cashflow": "구매 후 월 현금흐름(Buffer 유지)",
    "ltv": "LTV 한도",
    "required": "필요 대출금액",
    "credit_threshold": "신용대출 스트레스 문턱",
    "product": "상품 한도",
    "dti": "DTI 한도",
}


@dataclass(frozen=True)
class _Regime:
    """한 구간에서 계수가 고정된 다리 정보."""

    candidate: LoanLegCandidate
    actual_factor: Decimal
    assessment_factor: Decimal
    assessment_rate: Decimal


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def _subset_label(subset: Sequence[LoanLegCandidate]) -> ExcludedCombination:
    return ExcludedCombination(
        product_names=tuple(item.product_name for item in subset),
        candidate_ids=tuple(item.candidate_id for item in subset),
        reasons=(),
    )


def _build_regime(
    subset: Sequence[LoanLegCandidate],
    *,
    above_threshold: bool,
) -> tuple[tuple[_Regime, ...] | None, tuple[str, ...]]:
    """구간의 상환 계수를 확정한다. 확정할 수 없으면 (None, 결측)."""
    regimes: list[_Regime] = []
    missing: list[str] = []
    for candidate in subset:
        factor = candidate.assessment_payment_factor(above_threshold=above_threshold)
        rate = candidate.assessment_rate_for(above_threshold=above_threshold)
        if factor is None or rate is None:
            missing.append(f"{candidate.candidate_id}:assessment_rate_above_credit_threshold")
            continue
        regimes.append(
            _Regime(
                candidate=candidate,
                actual_factor=candidate.payment_factor,
                assessment_factor=factor,
                assessment_rate=rate,
            )
        )
    if missing:
        return None, tuple(missing)
    return tuple(regimes), ()


def _order_key(regime: _Regime, order: str) -> tuple[object, ...]:
    candidate = regime.candidate
    if order == "assessment_cost":
        primary: object = regime.assessment_factor
    elif order == "actual_cost":
        primary = regime.actual_factor
    else:
        # 미확인 유연성은 뒤로 보낸다 — 모르는 것을 우대하지 않는다.
        score = candidate.repayment_flexibility_score
        primary = (Decimal(1) if score is None else Decimal(0), -(score or Decimal(0)))
    # 동점은 candidate_id로 끊어 완전 결정론을 유지한다.
    return (primary, candidate.candidate_id)


def _allocate(
    regimes: Sequence[_Regime],
    budget: LoanCombinationBudget,
    policy: LoanCombinationPolicy,
    *,
    order: str,
    above_threshold: bool,
) -> tuple[dict[str, Decimal], tuple[str, ...]] | None:
    """한 구간·한 순서로 배분한다. 제약을 만족할 수 없으면 None.

    최소 실행금액부터 시작하는 이유는 예·적금과 같다 — 최소금액을 넣지 못하는
    조합은 애초에 실행할 수 없으므로 조합 자체를 버린다.
    """
    amounts = {item.candidate.candidate_id: item.candidate.floor_amount for item in regimes}

    remaining = {
        "dsr": budget.annual_dsr_capacity,
        "cashflow": budget.monthly_cashflow_capacity,
        "ltv": budget.ltv_limit_amount,
        "required": budget.required_amount,
    }
    credit_headroom = budget.credit_headroom_below_threshold
    if not above_threshold and credit_headroom is not None:
        remaining["credit_threshold"] = credit_headroom

    def consume(item: _Regime, amount: Decimal) -> None:
        remaining["dsr"] -= amount * item.assessment_factor * Decimal(12)
        remaining["cashflow"] -= amount * item.actual_factor
        remaining["required"] -= amount
        if item.candidate.kind is LoanLegKind.MORTGAGE:
            remaining["ltv"] -= amount
        if item.candidate.kind is LoanLegKind.CREDIT and "credit_threshold" in remaining:
            remaining["credit_threshold"] -= amount

    for item in regimes:
        consume(item, amounts[item.candidate.candidate_id])

    # 최소금액만으로 이미 예산을 넘으면 이 조합은 실행 불가다.
    if any(value < 0 for value in remaining.values()):
        return None
    for item in regimes:
        floor = amounts[item.candidate.candidate_id]
        cap = item.candidate.maximum_amount
        if cap is not None and floor > cap:
            return None
        dti = item.candidate.dti_limit_amount
        if dti is not None and floor > dti:
            return None

    binding: list[str] = []
    for item in sorted(regimes, key=lambda entry: _order_key(entry, order)):
        candidate = item.candidate
        current = amounts[candidate.candidate_id]

        # 남은 공유 예산을 이 다리의 계수로 나눠 배분 상한으로 환산한다.
        headroom: list[tuple[str, Decimal]] = [("required", remaining["required"])]
        if item.assessment_factor > 0:
            headroom.append(
                ("dsr", remaining["dsr"] / (item.assessment_factor * Decimal(12)))
            )
        if item.actual_factor > 0:
            headroom.append(("cashflow", remaining["cashflow"] / item.actual_factor))
        if candidate.kind is LoanLegKind.MORTGAGE:
            headroom.append(("ltv", remaining["ltv"]))
        if candidate.kind is LoanLegKind.CREDIT and "credit_threshold" in remaining:
            headroom.append(("credit_threshold", remaining["credit_threshold"]))
        if candidate.maximum_amount is not None:
            headroom.append(("product", candidate.maximum_amount - current))
        if candidate.dti_limit_amount is not None:
            headroom.append(("dti", candidate.dti_limit_amount - current))

        label, increment = min(headroom, key=lambda entry: entry[1])
        if label == "product":
            # 이 상한이 무엇인지는 후보를 만든 쪽이 안다. 여기서 "상품 한도"로
            # 단정하면 틀린 사유가 사용자에게 간다.
            label = candidate.maximum_amount_label
        # 원 단위로 **내림**한다. 두 가지를 동시에 해결한다.
        #
        # 1) 예산을 계수로 나눠 얻은 금액을 그대로 쓰면, 그 금액을 `pmt()`로 다시
        #    계산했을 때 Decimal 마지막 자리 차이로 예산을 미세하게 **넘는다**
        #    (실측: DSR 0.4000000000000000000000000002). 금액을 내리면 그 오차가
        #    흡수되고, 남는 방향은 항상 과소평가다.
        # 2) 이분탐색 결과가 소수점으로 남아 JSON에 `283520507.8125`처럼 실리던
        #    문제가 이 엔진에서는 생기지 않는다.
        increment = increment.to_integral_value(rounding=ROUND_DOWN)
        if increment <= policy.allocation_epsilon:
            binding.append(label)
            continue
        amounts[candidate.candidate_id] = current + increment
        consume(item, increment)
        binding.append(label)

    if all(value <= 0 for value in amounts.values()):
        return None
    return amounts, _dedupe(_CONSTRAINT_LABELS.get(name, name) for name in binding)


def _plan_from_amounts(
    regimes: Sequence[_Regime],
    amounts: Mapping[str, Decimal],
    budget: LoanCombinationBudget,
    policy: LoanCombinationPolicy,
    *,
    regime: CreditStressRegime,
    binding: tuple[str, ...],
    plan_id: str,
) -> LoanCombinationPlan:
    """배분액에서 조합안 지표를 계산한다.

    월 상환액은 계수 × 금액이 아니라 `pmt()`를 다시 부른다. 계수는 예산을 금액으로
    환산하기 위한 도구이고, 사용자에게 보이는 금액은 저장소 전역과 같은 함수에서
    나와야 한다.
    """
    legs: list[LoanLegAllocation] = []
    assumptions: list[str] = []
    for item in sorted(regimes, key=lambda entry: entry.candidate.candidate_id):
        candidate = item.candidate
        amount = amounts[candidate.candidate_id]
        if amount <= 0:
            continue
        monthly = pmt(amount, candidate.annual_rate, candidate.months)
        assessed = pmt(amount, item.assessment_rate, candidate.months)
        legs.append(
            LoanLegAllocation(
                candidate_id=candidate.candidate_id,
                product_id=candidate.product_id,
                product_name=candidate.product_name,
                option_name=candidate.option_name,
                kind=candidate.kind,
                amount=amount,
                monthly_payment=monthly,
                assessment_monthly_payment=assessed,
                total_interest=monthly * candidate.months - amount,
                annual_rate=candidate.annual_rate,
                assessment_annual_rate=item.assessment_rate,
                months=candidate.months,
                rate_type_name=candidate.rate_type_name,
                assumptions=candidate.assumptions,
            )
        )
        assumptions.extend(candidate.assumptions)

    total_amount = sum((leg.amount for leg in legs), Decimal(0))
    monthly_payment = sum((leg.monthly_payment for leg in legs), Decimal(0))
    assessment_payment = sum((leg.assessment_monthly_payment for leg in legs), Decimal(0))
    total_interest = sum((leg.total_interest for leg in legs), Decimal(0))

    extra_costs = [
        item.candidate.additional_financial_cost
        for item in regimes
        if amounts[item.candidate.candidate_id] > 0
    ]
    total_financial_cost = (
        None
        if any(cost is None for cost in extra_costs)
        else total_interest + sum((cost for cost in extra_costs if cost is not None), Decimal(0))
    )

    shortfall = max(budget.required_amount - total_amount, Decimal(0))
    covers = shortfall <= policy.recommendation_policy.loan_amount_tolerance

    surplus = (
        budget.post_purchase_monthly_income
        - budget.post_purchase_monthly_expense
        - budget.other_existing_monthly_debt_service
        - monthly_payment
    )
    stress_surplus = (
        budget.post_purchase_monthly_income
        - budget.post_purchase_monthly_expense
        - budget.other_existing_monthly_debt_service
        - assessment_payment
    )

    reasons: list[str] = []
    if shortfall == 0:
        reasons.append("필요 대출금액을 이 조합으로 전액 조달할 수 있습니다.")
    elif covers:
        reasons.append(
            f"계산 허용오차 이내의 자금 차이 {shortfall:,.0f}원이 남아 "
            "실행 전 은행 확정한도를 확인해야 합니다."
        )
    else:
        reasons.append(f"필요 대출금액 대비 {shortfall:,.0f}원이 부족합니다.")
    if binding:
        reasons.append(f"이 금액을 묶은 제약: {', '.join(binding)}")
    if regime is CreditStressRegime.ABOVE:
        reasons.append(
            "신용대출 잔액이 스트레스 문턱을 넘어 가산금리를 적용한 심사금리로 "
            "계산했습니다."
        )

    return LoanCombinationPlan(
        plan_id=plan_id,
        legs=tuple(legs),
        total_amount=total_amount,
        funding_shortfall=shortfall,
        covers_required_amount=covers,
        monthly_payment=monthly_payment,
        assessment_monthly_payment=assessment_payment,
        expected_dsr=dsr(
            existing_annual_debt_service=budget.existing_annual_debt_service,
            new_annual_debt_service=monthly_payment * Decimal(12),
            annual_income=budget.annual_income,
        ),
        assessment_dsr=dsr(
            existing_annual_debt_service=budget.existing_annual_debt_service,
            new_annual_debt_service=assessment_payment * Decimal(12),
            annual_income=budget.annual_income,
        ),
        post_purchase_monthly_surplus=surplus,
        stress_monthly_surplus=stress_surplus,
        total_interest=total_interest,
        total_financial_cost=total_financial_cost,
        credit_regime=regime,
        binding_constraints=binding,
        assumptions=_dedupe(assumptions),
        reasons=tuple(reasons),
    )


def _regime_premise_holds(
    plan: LoanCombinationPlan,
    budget: LoanCombinationBudget,
    *,
    above_threshold: bool,
) -> bool:
    """구간의 전제가 실제 배분에서 성립하는지 확인한다.

    문턱 위 구간은 "신용대출 잔액이 문턱을 넘는다"를 전제로 높은 심사금리를 썼다.
    배분 결과가 문턱을 넘지 않으면 그 전제가 거짓이므로 이 해를 버린다 — 남기면
    실제보다 엄격한 금리로 계산된 조합이 별개 대안처럼 늘어난다.
    """
    if plan.credit_regime is CreditStressRegime.NOT_APPLICABLE:
        # 신용대출 다리가 없으면 문턱과 무관하다. 이 분기가 없으면 기존 신용대출
        # 잔액이 이미 문턱을 넘은 차주의 **주담대 단독** 조합까지 버려진다.
        return not above_threshold
    threshold = budget.credit_stress_threshold
    existing = budget.existing_credit_loan_balance
    if threshold is None or existing is None:
        return not above_threshold
    new_credit = sum(
        (leg.amount for leg in plan.legs if leg.kind is LoanLegKind.CREDIT),
        Decimal(0),
    )
    crosses = existing + new_credit > threshold
    return crosses if above_threshold else not crosses


def _score_components(
    plan: LoanCombinationPlan,
    regimes: Sequence[_Regime],
    amounts: Mapping[str, Decimal],
    budget: LoanCombinationBudget,
    policy: RecommendationPolicy,
) -> CombinationScoreComponents:
    """§14 다섯 항목을 조합 기준으로 계산한다(총비용은 뒤에서 채운다).

    단일 옵션과 **같은 공식**을 쓰고 입력만 조합 합계로 바꾼다. 조합 전용 공식을
    만들면 단일 옵션 순위와 조합 순위가 서로 모순될 수 있다.
    """
    # §14.1 상환가능성 — 조합 DSR을 내부 안전기준과 비교한다.
    repayment_capacity = _clamp(Decimal(1) - plan.expected_dsr / budget.safe_dsr)

    # §14.3 위기대응력 — 심사금리 기준 잉여가 Buffer를 얼마나 덮는가.
    crisis_resilience = (
        None
        if budget.buffer_target == 0
        else _clamp(plan.stress_monthly_surplus / budget.buffer_target)
    )

    # §14.4 금리안정성 — 심사 상환액 증가율.
    if plan.monthly_payment == 0:
        interest_stability: Decimal | None = Decimal(1)
    elif policy.maximum_payment_increase_ratio == 0:
        interest_stability = (
            Decimal(1)
            if plan.assessment_monthly_payment == plan.monthly_payment
            else Decimal(0)
        )
    else:
        increase = max(
            plan.assessment_monthly_payment - plan.monthly_payment, Decimal(0)
        ) / plan.monthly_payment
        interest_stability = _clamp(
            Decimal(1) - increase / policy.maximum_payment_increase_ratio
        )

    # §14.5 상환유연성 — 다리별 점수를 배분액으로 가중평균한다. 하나라도 모르면
    # 조합 값을 만들지 않는다(A-10이 가중치를 재정규화한다).
    weights: list[tuple[Decimal, Decimal]] = []
    unknown_flexibility = False
    for item in regimes:
        amount = amounts[item.candidate.candidate_id]
        if amount <= 0:
            continue
        score = item.candidate.repayment_flexibility_score
        if score is None:
            unknown_flexibility = True
            break
        weights.append((score, amount))
    total_weight = sum((weight for _score, weight in weights), Decimal(0))
    repayment_flexibility = (
        None
        if unknown_flexibility or total_weight <= 0
        else sum((score * weight for score, weight in weights), Decimal(0)) / total_weight
    )

    return CombinationScoreComponents(
        repayment_capacity=repayment_capacity,
        total_cost=None,
        crisis_resilience=crisis_resilience,
        interest_stability=interest_stability,
        repayment_flexibility=repayment_flexibility,
    )


def _cost_scores(
    plans: Sequence[LoanCombinationPlan],
    policy: RecommendationPolicy,
) -> dict[str, Decimal]:
    """총비용을 조합끼리 정규화한다(부록 A-1 역방향 정규화).

    §14.2는 대출금액과 기간을 맞추고 비교하라고 정한다. 필요금액을 전액 조달하지
    못하는 조합은 덜 빌려서 비용이 작을 뿐이므로 같은 기준이 아니다 — 전액 조합만
    비교하고, 비용 항목이 하나라도 미확인이면 아예 점수화하지 않는다.
    """
    covering = [
        plan for plan in plans if plan.funding_shortfall <= policy.loan_amount_tolerance
    ]
    if not covering or any(plan.total_financial_cost is None for plan in covering):
        return {}
    costs = {
        plan.plan_id: cost
        for plan in covering
        if (cost := plan.total_financial_cost) is not None
    }
    minimum = min(costs.values())
    maximum = max(costs.values())
    if maximum == minimum:
        return dict.fromkeys(costs, Decimal(1))
    return {
        key: Decimal(1) - (value - minimum) / (maximum - minimum)
        for key, value in costs.items()
    }


def _apply_score(
    plan: LoanCombinationPlan,
    *,
    cost_score: Decimal | None,
    policy: RecommendationPolicy,
) -> LoanCombinationPlan:
    """§14 가중합. 결측 항목은 부록 A-10대로 가중치를 재정규화한다."""
    assert plan.score_components is not None
    components = replace(plan.score_components, total_cost=cost_score)
    values = {
        "repayment_capacity": components.repayment_capacity,
        "total_cost": components.total_cost,
        "crisis_resilience": components.crisis_resilience,
        "interest_stability": components.interest_stability,
        "repayment_flexibility": components.repayment_flexibility,
    }
    known_weight = sum(
        (policy.weights[name] for name, value in values.items() if value is not None),
        Decimal(0),
    )
    missing = tuple(name for name, value in values.items() if value is None)

    if known_weight == 0 or known_weight < policy.minimum_score_completeness:
        return replace(
            plan,
            score=None,
            score_status=ScoreStatus.UNAVAILABLE,
            score_completeness=known_weight,
            score_components=components,
            missing_score_components=missing,
        )

    weighted = sum(
        (
            policy.weights[name] * value
            for name, value in values.items()
            if value is not None
        ),
        Decimal(0),
    )
    return replace(
        plan,
        score=Decimal(100) * weighted / known_weight,
        score_status=ScoreStatus.COMPLETE if not missing else ScoreStatus.PROVISIONAL,
        score_completeness=known_weight,
        score_components=components,
        missing_score_components=missing,
    )


def _plan_sort_key(plan: LoanCombinationPlan, required_amount: Decimal) -> tuple[object, ...]:
    """오름차순 정렬 키. 앞쪽이 좋은 조합이 되도록 좋은 값은 음수로 넣는다.

    **자금 충족을 §14 점수보다 먼저 본다.** §14.2는 "대출금액과 기간을 동일하게
    맞추고" 비교하라고 정하는데, 조달액이 서로 다른 조합에 §14를 그대로 적용하면
    §14.1 상환가능성(가중치 0.30)이 낮은 DSR을 우대하므로 **덜 빌리는 조합이 항상
    이긴다.** 실측에서 주담대 단독 2.0억(부족 2.0억)이 58.2점으로 조합 2.33억
    (부족 1.67억)의 44.7점을 눌렀다. 집을 사려는 사용자에게는 뒤집힌 순서다.

    그래서 충족률로 먼저 묶고, **같은 조달 수준 안에서** §14로 우열을 가린다 —
    그것이 §14가 설계된 용법이다. 예·적금 포트폴리오가 `objective_score`보다
    `coverage_ratio`를 먼저 보는 것과 같은 규율이다(`savings/portfolio.py`의
    `_plan_is_better`).

    조달액이 필요금액을 넘는 일은 없다(필요금액이 예산 상한 중 하나다). 따라서
    충족률 우선이 과다 차입을 권하는 방향으로 작동하지 않는다.

    점수가 없는 조합을 점수 있는 조합보다 앞에 두지 않는다 — 점수 미확인을
    "나쁘지 않음"으로 읽으면 근거 없는 1위가 나온다.
    """
    coverage = (
        Decimal(1)
        if required_amount <= 0
        else min(plan.total_amount / required_amount, Decimal(1))
    )
    return (
        0 if plan.covers_required_amount else 1,
        -coverage,
        0 if plan.score is not None else 1,
        -(plan.score or Decimal(0)),
        -plan.total_amount,
        plan.leg_count,  # 같은 금액이면 단순한 조합이 낫다
        plan.plan_id,  # 완전 결정론을 위한 마지막 끊기
    )


def build_loan_combinations(
    candidates: Sequence[LoanLegCandidate],
    budget: LoanCombinationBudget,
    *,
    policy: LoanCombinationPolicy = DEFAULT_COMBINATION_POLICY,
    combination_gate: CombinationGate | None = None,
) -> LoanCombinationResult:
    """실행 가능한 조합안을 찾아 §14 점수 내림차순 상위 ``top_n``개를 돌려준다.

    ``combination_gate``는 상품명 목록을 받아 동시 실행 가능 여부를 답하는 함수다
    (`data_pipeline/curated/loan_combinations.resolve_combination`을 감싼 것).
    **넘기지 않으면 다리가 2개 이상인 조합을 만들지 않는다** — 중복 이용 가능
    여부를 모른 채 조합하면 존재할 수 없는 대안을 추천하기 때문이다.
    """
    unique_ids = [item.candidate_id for item in candidates]
    if len(unique_ids) != len(set(unique_ids)):
        raise ValueError("candidate_id는 중복될 수 없습니다.")

    if not candidates:
        return LoanCombinationResult(
            status=CombinationStatus.UNRESOLVED,
            missing_inputs=("loan_leg_candidates",),
            reasons=("조합할 대출 후보가 없습니다. 후보 0건은 '가능한 조합이 없음'과 다릅니다.",),
            policy_note=policy.recommendation_policy.policy_note,
        )

    plans: list[LoanCombinationPlan] = []
    plan_context: dict[str, tuple[tuple[_Regime, ...], Mapping[str, Decimal]]] = {}
    blocked: list[ExcludedCombination] = []
    unresolved: list[ExcludedCombination] = []
    infeasible: list[ExcludedCombination] = []
    seen_allocations: set[tuple[tuple[str, Decimal], ...]] = set()
    considered = 0
    feasible_subsets = 0

    max_legs = min(policy.max_legs, len(candidates))
    for leg_count in range(1, max_legs + 1):
        for subset in combinations(candidates, leg_count):
            # 같은 상품의 옵션 두 개를 동시에 고르지 않는다 — 한 상품을 두 계좌처럼
            # 쓰는 것은 별개 사실이고 확인되지 않았다(예적금과 같은 규율).
            if len({item.product_id for item in subset}) != len(subset):
                continue
            considered += 1

            gate_outcome = _check_gate(subset, combination_gate)
            if gate_outcome is not None:
                bucket, excluded = gate_outcome
                (blocked if bucket == "blocked" else unresolved).append(excluded)
                continue

            subset_plans = _plans_for_subset(
                subset,
                budget,
                policy,
                unresolved=unresolved,
                infeasible=infeasible,
            )
            if subset_plans:
                feasible_subsets += 1
            for regimes, amounts, plan in subset_plans:
                fingerprint = tuple(
                    sorted((leg.candidate_id, leg.amount) for leg in plan.legs)
                )
                if fingerprint in seen_allocations:
                    continue
                seen_allocations.add(fingerprint)
                plans.append(plan)
                plan_context[plan.plan_id] = (regimes, amounts)

    if not plans:
        return LoanCombinationResult(
            status=CombinationStatus.INFEASIBLE,
            considered_subsets=considered,
            blocked=tuple(blocked),
            unresolved=tuple(unresolved),
            infeasible=tuple(infeasible),
            reasons=(
                "DSR·현금흐름·LTV 예산과 상품 한도를 동시에 만족하는 조합이 없습니다.",
            ),
            policy_note=policy.recommendation_policy.policy_note,
        )

    scored = [
        replace(
            plan,
            score_components=_score_components(
                plan,
                plan_context[plan.plan_id][0],
                plan_context[plan.plan_id][1],
                budget,
                policy.recommendation_policy,
            ),
        )
        for plan in plans
    ]
    cost_scores = _cost_scores(scored, policy.recommendation_policy)
    scored = [
        _apply_score(
            plan,
            cost_score=cost_scores.get(plan.plan_id),
            policy=policy.recommendation_policy,
        )
        for plan in scored
    ]
    scored.sort(key=lambda plan: _plan_sort_key(plan, budget.required_amount))

    # 자리를 채우려고 탈락한 조합을 끼워 넣지 않는다. 통과한 것이 top_n보다 적으면
    # 적은 대로 준다 — "5개 중 5위"가 "실행 가능"으로 읽히면 안 된다.
    top = tuple(scored[: policy.top_n])
    status = (
        CombinationStatus.COMPLETE
        if any(plan.covers_required_amount for plan in top)
        else CombinationStatus.PARTIAL
    )
    reasons: list[str] = [
        f"조합 후보 {considered}개 중 {len(scored)}개가 제약을 통과했고 "
        f"상위 {len(top)}개를 제시합니다."
    ]
    if status is CombinationStatus.PARTIAL:
        reasons.append(
            "어느 조합도 필요 대출금액을 전액 조달하지 못합니다. "
            "자기자본을 더 넣거나 목표 금액을 조정해야 합니다."
        )
    if len(scored) > len(top):
        reasons.append(
            f"제약을 통과한 나머지 {len(scored) - len(top)}개는 점수가 낮아 제외했습니다."
        )
    return LoanCombinationResult(
        status=status,
        plans=top,
        considered_subsets=considered,
        feasible_subsets=feasible_subsets,
        blocked=tuple(blocked),
        unresolved=tuple(unresolved),
        infeasible=tuple(infeasible),
        reasons=tuple(reasons),
        policy_note=policy.recommendation_policy.policy_note,
    )


def _check_gate(
    subset: Sequence[LoanLegCandidate],
    gate: CombinationGate | None,
) -> tuple[str, ExcludedCombination] | None:
    """검수표로 동시 실행 가능 여부를 확인한다. 통과하면 None.

    다리가 1개면 조합이 아니므로 확인할 것이 없다. 2개 이상인데 게이트가 없으면
    **만들지 않는다** — 확인하지 않은 조합을 내보내지 않기 위한 기본값이다.
    """
    if len(subset) <= 1:
        return None
    names = tuple(item.product_name for item in subset)
    base = _subset_label(subset)
    if gate is None:
        return "unresolved", replace(
            base,
            reasons=(
                "중복 이용 가능 여부를 확인하는 검수표가 주어지지 않아 "
                "여러 상품을 함께 쓰는 조합을 만들지 않았습니다.",
            ),
            missing_inputs=("loan_combination_gate",),
        )
    verdict = gate(names)  # type: ignore[operator]
    if verdict.is_executable:
        return None
    if verdict.blocking_pairs:
        return "blocked", replace(
            base,
            reasons=tuple(
                f"{first} + {second}: {note}"
                for (first, second), note in verdict.blocking_pairs
            ),
            sources=verdict.sources,
        )
    return "unresolved", replace(
        base,
        reasons=tuple(
            f"{first} + {second}: 동시 실행 가능 여부를 확인하지 못했습니다."
            for first, second in verdict.unknown_pairs
        ),
        missing_inputs=tuple(
            f"duplicate_use:{first}+{second}" for first, second in verdict.unknown_pairs
        ),
    )


def _plans_for_subset(
    subset: Sequence[LoanLegCandidate],
    budget: LoanCombinationBudget,
    policy: LoanCombinationPolicy,
    *,
    unresolved: list[ExcludedCombination],
    infeasible: list[ExcludedCombination],
) -> list[tuple[tuple[_Regime, ...], Mapping[str, Decimal], LoanCombinationPlan]]:
    """부분집합 하나에서 구간·순서를 모두 시도해 조합안 후보를 만든다."""
    has_credit = any(item.kind is LoanLegKind.CREDIT for item in subset)
    base = _subset_label(subset)

    if has_credit and budget.credit_headroom_below_threshold is None:
        # 문턱 판정에 필요한 값이 없다. 0으로 뭉개면 문턱을 넘는 조합에 가산금리가
        # 빠져 한도가 과대평가된다.
        unresolved.append(
            replace(
                base,
                reasons=(
                    "신용대출 스트레스 문턱 판정에 필요한 기존 잔액 또는 문턱값이 "
                    "없어 계산하지 않았습니다.",
                ),
                missing_inputs=("existing_credit_loan_balance",),
            )
        )
        return []

    regimes_to_try: list[tuple[bool, CreditStressRegime]] = [
        (False, CreditStressRegime.BELOW if has_credit else CreditStressRegime.NOT_APPLICABLE)
    ]
    if has_credit:
        regimes_to_try.append((True, CreditStressRegime.ABOVE))

    results: list[tuple[tuple[_Regime, ...], Mapping[str, Decimal], LoanCombinationPlan]] = []
    any_feasible = False
    for above_threshold, regime_label in regimes_to_try:
        regimes, missing = _build_regime(subset, above_threshold=above_threshold)
        if regimes is None:
            unresolved.append(
                replace(
                    base,
                    reasons=(
                        "신용대출 잔액이 문턱을 넘는 구간의 심사금리를 확정하지 못해 "
                        "그 구간을 계산하지 않았습니다. 문턱 아래 금리로 계산하면 "
                        "가산금리가 빠져 한도가 과대평가됩니다.",
                    ),
                    missing_inputs=missing,
                )
            )
            continue

        for order in _FILL_ORDERS:
            allocated = _allocate(
                regimes,
                budget,
                policy,
                order=order,
                above_threshold=above_threshold,
            )
            if allocated is None:
                continue
            amounts, binding = allocated
            plan_id = "|".join(
                (
                    *(sorted(item.candidate.candidate_id for item in regimes)),
                    regime_label.value,
                    order,
                )
            )
            plan = _plan_from_amounts(
                regimes,
                amounts,
                budget,
                policy,
                regime=regime_label,
                binding=binding,
                plan_id=plan_id,
            )
            if not plan.legs:
                continue
            if not _regime_premise_holds(plan, budget, above_threshold=above_threshold):
                continue
            if not _minimums_respected(regimes, amounts):
                continue
            any_feasible = True
            results.append((regimes, amounts, plan))

    if not any_feasible and not results:
        infeasible.append(
            replace(
                base,
                reasons=(
                    "이 조합은 DSR·현금흐름·LTV 예산 또는 상품 최소·최대 한도를 "
                    "동시에 만족하지 못합니다.",
                ),
            )
        )
    return results


def _minimums_respected(
    regimes: Sequence[_Regime],
    amounts: Mapping[str, Decimal],
) -> bool:
    """배분된 다리가 상품 최소 실행금액을 지켰는지.

    금액을 최소금액까지 끌어올리는 선택지는 없다 — 그러면 애초에 금액을 낮춘
    DSR·LTV·현금흐름 제약을 위반한다(`LoanComputation` docstring과 같은 판단).
    """
    for item in regimes:
        amount = amounts[item.candidate.candidate_id]
        minimum = item.candidate.minimum_amount
        if amount > 0 and minimum is not None and amount < minimum:
            return False
    return True


__all__ = ["build_loan_combinations"]
