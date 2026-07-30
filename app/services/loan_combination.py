"""대출 계산 결과를 조합 엔진 입력으로 옮기고 조합안을 만든다.

목적:
    `simulate_loan_options()`가 낸 옵션별 한도를 다리 후보로 바꿔
    `build_loan_combinations()`에 넘긴다. 규제표·검수표를 아는 계층은 여기뿐이며,
    조합 엔진은 순수 계산으로 남는다.

왜 `LoanSimulationResult`를 바꾸지 않는가:
    조합 엔진의 다리 상한으로 **옵션의 단일 대출 한도(`LoanComputation.amount`)를
    그대로 쓴다.** 그 값은 이미 `min(LTV, 상품, DTI, DSR, 필요액)`이라 그 다리가
    혼자서도 넘을 수 없는 상한이고, 조합에서는 공유 예산이 더 좁히기만 한다.
    따라서 안전한 상한이다.

    LTV가 두 번 적용되는 셈이지만(단일 한도 안에서 한 번, 공유 LTV 예산에서 한 번)
    상한을 두 번 씌우는 것은 느슨해지지 않는다. 반대로 상품 한도·DTI 환산액을
    복원하려고 `LoanComputation`에 필드를 늘리면 이미 쓰이는 계약이 넓어진다.
    **과소평가는 안전하고 계약 확장은 위험하므로** 전자를 택했다.

근거:
    §9.1 LoanMax 제약 목록, §13.2/A-12 DSR 범위, `stress_dsr.py`의 신용대출 잔액
    문턱, 그리고 중복 이용 검수표(`curated/loan_combinations.py`).
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.data_pipeline.curated.loan_combinations import (
    collateral_group,
    resolve_combination,
)
from app.engines.loan.combination import build_loan_combinations
from app.engines.loan.combination_models import (
    DEFAULT_COMBINATION_POLICY,
    CombinationStatus,
    LoanCombinationBudget,
    LoanCombinationPolicy,
    LoanCombinationResult,
    LoanLegCandidate,
    LoanLegKind,
)
from app.regulations.mortgage_limits import RegulationZone
from app.regulations.stress_dsr import (
    CREDIT_LOAN_STRESS_THRESHOLD,
    StressLoanKind,
    get_stress_rate,
    resolve_stress_region,
    stressed_annual_rate,
)
from app.services.loan_simulation import LoanSimulationRequest, LoanSimulationResult
from app.services.recommendation import LoanRecommendationSupplement

_KIND_BY_GROUP = {
    "MORTGAGE": LoanLegKind.MORTGAGE,
    "CREDIT": LoanLegKind.CREDIT,
}


def _option_name(computation: object) -> str:
    """추천 계층과 같은 옵션 이름 규칙을 쓴다 — 화면에서 이름이 갈리지 않게."""
    option = getattr(computation, "option", None)
    if option is None:
        return "옵션 정보 없음"
    parts = (
        option.mortgage_type_name,
        option.repayment_type_name,
        option.rate_type_name,
    )
    return " / ".join(part for part in parts if part) or "기본 옵션"


def _above_threshold_credit_rate(
    request: LoanSimulationRequest,
    annual_rate: Decimal,
    *,
    below_threshold_assessment_rate: Decimal,
) -> Decimal | None:
    """신용대출 잔액이 문턱을 넘었을 때 적용할 심사금리. 확정 불가면 None.

    문턱을 **넘은 상태**의 가산금리를 규제표에 직접 물어본다. 조합이 신용대출을
    새로 빌려 잔액이 문턱을 넘을 수 있는데, `request.credit_loan_balance`는 기존
    잔액이라 그 상태의 금리를 담고 있지 않기 때문이다.

    계산된 값이 문턱 아래 심사금리보다 **낮으면 모순**이다(문턱 위가 더 느슨할 수
    없다). 그런 경우 억지로 맞추지 않고 None을 돌려준다 — 조합 엔진이 문턱 위
    구간을 평가하지 않으므로 신용대출이 문턱까지만 배분되고, 그쪽이 보수적이다.
    억지로 끌어올리면 근거 없는 금리를 만들어내고, 그대로 넘기면 후보 생성이
    `ValueError`로 터져 조합 전체가 죽는다.
    """
    stress = get_stress_rate(
        resolve_stress_region(
            is_capital_region=request.is_capital_region,
            is_regulated_region=request.zone is not RegulationZone.NON_REGULATED,
        ),
        StressLoanKind.CREDIT,
        as_of=request.as_of,
        credit_loan_balance=CREDIT_LOAN_STRESS_THRESHOLD + Decimal(1),
        allow_unverified=request.allow_unverified_regulation,
    )
    if stress is None:
        return None
    above = stressed_annual_rate(annual_rate, stress)
    if above < below_threshold_assessment_rate:
        return None
    return above


def build_combination_legs(
    request: LoanSimulationRequest,
    result: LoanSimulationResult,
    *,
    supplements: Mapping[str, LoanRecommendationSupplement] | None = None,
) -> tuple[tuple[LoanLegCandidate, ...], tuple[str, ...]]:
    """실행 가능한 옵션을 조합 다리 후보로 바꾼다.

    반환값은 ``(다리 후보, 제외 사유)``다. 확정할 수 없는 값이 있으면 그 다리를
    **넣지 않고** 이름을 남긴다 — 추측해 채우면 조합 전체가 근거를 잃는다.
    """
    legs: list[LoanLegCandidate] = []
    skipped: list[str] = []
    lookup = supplements or {}

    for index, computation in enumerate(result.executable, start=1):
        name = computation.product_name
        group = collateral_group(name)
        if group is None:
            # 담보 묶음을 모르면 LTV 예산에 넣을지 알 수 없다. OTHER로 떨어뜨리면
            # LTV에서 빠져 한도가 커지는 방향으로 틀린다.
            skipped.append(f"{name}: 담보 구분이 검수표에 없어 조합에서 제외했습니다.")
            continue
        if computation.annual_rate is None:
            skipped.append(f"{name}: 적용 금리를 확정하지 못해 조합에서 제외했습니다.")
            continue
        if computation.dsr_annual_rate is None:
            # 심사금리를 모르면 DSR 예산을 얼마나 먹는지 모른다. 실제 금리로
            # 대체하면 스트레스가 빠져 조합 한도가 과대평가된다.
            skipped.append(
                f"{name}: 스트레스 DSR 심사금리를 확정하지 못해 조합에서 제외했습니다."
            )
            continue
        months = computation.months if computation.months is not None else request.months

        kind = _KIND_BY_GROUP[group]
        above_rate = (
            _above_threshold_credit_rate(
                request,
                computation.annual_rate,
                below_threshold_assessment_rate=computation.dsr_annual_rate,
            )
            if kind is LoanLegKind.CREDIT
            else None
        )
        supplement = lookup.get(name)
        option_name = _option_name(computation)
        legs.append(
            LoanLegCandidate(
                candidate_id=f"leg:{index}:{name}:{option_name}",
                # 원천 데이터에 상품 ID가 없어 상품명이 곧 식별자다(9건 안에서
                # 고유하다). 같은 상품의 옵션 두 개를 동시에 고르지 않는 규칙이
                # 이 값으로 동작한다.
                product_id=name,
                product_name=name,
                option_name=option_name,
                kind=kind,
                annual_rate=computation.annual_rate,
                assessment_annual_rate=computation.dsr_annual_rate,
                months=months,
                # 단일 대출 한도를 다리 상한으로 쓴다(모듈 docstring 참조).
                maximum_amount=computation.amount,
                # 그 값은 상품 한도가 아니라 여러 상한의 최솟값이다. 이름을 정확히
                # 붙여야 조합안의 "묶은 제약"이 사용자에게 거짓말하지 않는다.
                maximum_amount_label="이 옵션의 단일 대출 한도(LTV·상품·DTI·DSR 최솟값)",
                minimum_amount=computation.product_minimum_amount,
                # DTI는 위 상한에 이미 반영돼 있어 따로 넣지 않는다. 다시 넣으면
                # 같은 제약을 두 번 세는 셈이고, 그쪽이 더 좁으면 과소평가된다.
                dti_limit_amount=None,
                assessment_annual_rate_above_credit_threshold=above_rate,
                additional_financial_cost=(
                    None if supplement is None else supplement.additional_financial_cost
                ),
                repayment_flexibility_score=(
                    None if supplement is None else supplement.repayment_flexibility_score
                ),
                rate_type_name=(
                    None if computation.option is None else computation.option.rate_type_name
                ),
                assumptions=computation.assumptions,
            )
        )

    return tuple(legs), tuple(dict.fromkeys(skipped))


def build_combination_budget(
    request: LoanSimulationRequest,
    result: LoanSimulationResult,
) -> LoanCombinationBudget | None:
    """공유 예산을 만든다. LTV를 확정하지 못했으면 None.

    LTV를 모른 채 조합하면 주담대 다리에 상한이 사라져 한도가 과대평가된다.
    """
    if result.ltv is None or result.ltv.amount is None:
        return None
    borrower = request.borrower
    return LoanCombinationBudget(
        annual_income=borrower.annual_income,
        existing_annual_debt_service=borrower.existing_annual_debt_service,
        safe_dsr=borrower.safe_dsr,
        post_purchase_monthly_income=borrower.post_purchase_monthly_income,
        post_purchase_monthly_expense=borrower.post_purchase_monthly_expense,
        other_existing_monthly_debt_service=borrower.other_existing_monthly_debt_service,
        buffer_target=borrower.buffer_target,
        ltv_limit_amount=result.ltv.amount,
        required_amount=request.required_amount,
        credit_stress_threshold=CREDIT_LOAN_STRESS_THRESHOLD,
        # 기존 신용대출 잔액. None이면 조합 엔진이 신용대출이 든 조합을 계산하지
        # 않고 결측으로 남긴다.
        existing_credit_loan_balance=request.credit_loan_balance,
    )


def combine_loan_options(
    request: LoanSimulationRequest,
    result: LoanSimulationResult,
    *,
    supplements: Mapping[str, LoanRecommendationSupplement] | None = None,
    policy: LoanCombinationPolicy = DEFAULT_COMBINATION_POLICY,
) -> LoanCombinationResult:
    """계산 결과에서 조합안 상위 N개를 만든다.

    중복 이용 검수표를 게이트로 넘긴다 — 이것이 없으면 조합 엔진은 다리 2개 이상인
    조합을 아예 만들지 않는다.
    """
    budget = build_combination_budget(request, result)
    if budget is None:
        return LoanCombinationResult(
            status=CombinationStatus.UNRESOLVED,
            missing_inputs=("ltv_limit_amount",),
            reasons=(
                "LTV 한도를 확정하지 못해 조합을 계산하지 않았습니다. "
                "상한 없이 조합하면 대출 가능액이 과대평가됩니다.",
            ),
        )

    legs, skipped = build_combination_legs(request, result, supplements=supplements)
    if not legs:
        return LoanCombinationResult(
            status=CombinationStatus.UNRESOLVED,
            missing_inputs=("loan_leg_candidates",),
            reasons=(
                *skipped,
                "조합할 수 있는 실행 가능 옵션이 없습니다. "
                "후보 0건은 '가능한 조합이 없음'과 다른 상태입니다.",
            ),
        )

    combined = build_loan_combinations(
        legs,
        budget,
        policy=policy,
        combination_gate=_gate,
    )
    if not skipped:
        return combined
    # 제외한 다리를 조용히 버리지 않는다 — 무엇이 빠졌는지 결과에 남긴다.
    return LoanCombinationResult(
        status=combined.status,
        plans=combined.plans,
        considered_subsets=combined.considered_subsets,
        feasible_subsets=combined.feasible_subsets,
        blocked=combined.blocked,
        unresolved=combined.unresolved,
        infeasible=combined.infeasible,
        missing_inputs=combined.missing_inputs,
        reasons=(*combined.reasons, *skipped),
        policy_note=combined.policy_note,
    )


def _gate(product_names: Sequence[str]):  # noqa: ANN202 - Protocol 구조만 맞추면 된다
    return resolve_combination(product_names)


__all__ = [
    "build_combination_budget",
    "build_combination_legs",
    "combine_loan_options",
]
