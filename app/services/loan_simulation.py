from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.data_pipeline.adapters.loan_engine_adapter import (
    BorrowerFinancialState,
    LoanComputation,
    LoanOptionAdaptation,
    PolicyLimits,
    adapt_handoff_for_loan_max,
    compute_loan_option,
)
from app.regulations.mortgage_limits import (
    BANK_DSR_LIMIT,
    DTI_RATIOS,
    HousingStatus,
    RegulationZone,
    ResolvedPolicyLimit,
    resolve_dti_limit_amount,
    resolve_ltv_limit_amount,
)
from app.regulations.stress_dsr import (
    StressLoanKind,
    StressRate,
    get_stress_rate,
    resolve_stress_region,
)
from app.rule_engine.product_packs.handoff import (
    ProductCandidate,
    ProductEngineHandoff,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import EvaluationStatus, ProductCategory
from app.rule_engine.product_packs.registry import ProductRulePackRegistry

# 규제표 → 상품 판정 → 어댑터 → 계산까지를 하나의 요청으로 잇는 조립 계층이다.
# 이 계층이 생기기 전에는 `PolicyLimits`를 테스트에서만 만들었고, 규제 해석기
# (`resolve_ltv_limit_amount`/`resolve_dti_limit_amount`)를 실제로 부르는 코드가
# 없었다 — 표는 있는데 아무도 안 쓰는 상태였다.
#
# 계층을 나눈 이유는 각자의 규율이 다르기 때문이다:
#   - 규제표는 출처·시행일이 붙은 상수만 안다.
#   - Rule Pack은 자격만 판정하고 금액을 모른다.
#   - 어댑터는 규제표를 모른 채 "채워진 입력"만 조립한다.
#   - 엔진은 순수 계산이다.
# 여기서만 넷을 다 알고, 그래서 **결측이 발생하는 지점도 여기에 모인다.**
#
# 결측 규약은 하위 계층과 같다 — 모르면 UNKNOWN을 반환하고 임의값으로 채우지
# 않는다. 특히 LTV·DTI를 확정하지 못했을 때 0이나 무한대를 넣지 않는다.
# 0을 넣으면 "빌릴 수 없음"으로, 큰 값을 넣으면 "제약 없음"으로 읽혀 둘 다 거짓말이다.


@dataclass(frozen=True)
class LoanSimulationRequest:
    """대출 시뮬레이션 한 건의 입력.

    `as_of`는 오늘 날짜가 아니라 **적용할 규제의 기준일**이다. 경과규정 대상
    차주(시행일 전에 대출신청 접수 또는 매매계약·계약금 납부를 마친 경우)는
    종전 규정을 적용받으므로 그 시점을 넘긴다.
    """

    borrower: BorrowerFinancialState
    user_facts: Mapping[str, object]
    house_price: Decimal
    zone: RegulationZone
    housing_status: HousingStatus
    is_capital_region: bool
    required_amount: Decimal
    months: int
    as_of: date
    dti_region: str = "SEOUL"
    rate_selection: str = "avg"
    for_house_purchase: bool = True
    allow_unverified_regulation: bool = False
    # 신용대출 스트레스 금리는 잔액 1억원 초과 시에만 붙는다. 모르면 신용대출을
    # 계산하지 못한다 — 0으로 뭉개면 한도가 과대평가되기 때문이다.
    credit_loan_balance: Decimal | None = None


@dataclass(frozen=True)
class LoanSimulationResult:
    """상품별 계산 결과와 그 근거.

    `executable`/`not_executable`/`unresolved`/`rejected`는 서로 겹치지 않으며
    이유가 다르다. 뭉뚱그리면 "왜 이 상품이 빠졌는가"에 답할 수 없다:
      - executable      계산됐고 실행 가능
      - not_executable  계산됐지만 상품 최소 실행금액 미달
      - unresolved      입력을 확정하지 못해 계산 자체를 못 함(UNKNOWN)
      - rejected        Rule Pack 자격 판정 탈락(FAIL)
    """

    executable: tuple[LoanComputation, ...] = field(default_factory=tuple)
    not_executable: tuple[LoanComputation, ...] = field(default_factory=tuple)
    unresolved: tuple[LoanOptionAdaptation, ...] = field(default_factory=tuple)
    rejected: tuple[LoanOptionAdaptation, ...] = field(default_factory=tuple)
    ltv: ResolvedPolicyLimit | None = None
    policy_as_of: date | None = None
    policy_sources: tuple[str, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_resolved(self) -> bool:
        """규제 한도를 확정해 계산을 시도할 수 있었는지."""
        return not self.missing_inputs

    @property
    def best(self) -> LoanComputation | None:
        """실행 가능한 것 중 가장 많이 빌릴 수 있는 옵션."""
        if not self.executable:
            return None
        return max(self.executable, key=lambda computation: computation.amount)


def simulate_loan_options(
    request: LoanSimulationRequest,
    candidates: Iterable[ProductCandidate],
    *,
    registry: ProductRulePackRegistry | None = None,
) -> LoanSimulationResult:
    """요청 하나를 규제 해석 → 자격 판정 → 조립 → 계산까지 통과시킨다.

    규제 한도를 확정하지 못하면 상품 판정으로 넘어가지 않고 즉시 결측을 보고한다.
    LTV를 모르는 채 계산한 금액은 의미가 없고, 그걸 상품별로 늘어놓으면 근거 없는
    숫자만 늘어나기 때문이다.
    """
    ltv = resolve_ltv_limit_amount(
        house_price=request.house_price,
        zone=request.zone,
        status=request.housing_status,
        is_capital_region=request.is_capital_region,
        as_of=request.as_of,
        for_house_purchase=request.for_house_purchase,
        allow_unverified=request.allow_unverified_regulation,
    )

    dti_ratio = DTI_RATIOS.get(request.dti_region)
    sources = tuple(ltv.sources) + ((dti_ratio.source,) if dti_ratio is not None else ())

    missing: list[str] = []
    if ltv.amount is None:
        missing.extend(ltv.missing_inputs or ("ltv_limit_amount",))
    if dti_ratio is None:
        missing.append("dti_ratio")

    if missing:
        return LoanSimulationResult(
            ltv=ltv,
            policy_as_of=request.as_of,
            policy_sources=sources,
            missing_inputs=tuple(dict.fromkeys(missing)),
            notes=_regulation_notes(ltv, dti_ratio, request),
        )

    assert ltv.amount is not None and dti_ratio is not None

    def resolve_dti(annual_rate: Decimal, months: int) -> Decimal | None:
        # 옵션마다 금리·만기가 다르므로 DTI 한도도 옵션마다 다시 역산한다.
        # 하나를 공유하면 금리가 낮은 옵션의 한도가 그대로 높은 옵션에 쓰인다.
        return resolve_dti_limit_amount(
            annual_income=request.borrower.annual_income,
            dti_ratio=dti_ratio.ratio,
            other_annual_interest=request.borrower.existing_annual_debt_service,
            annual_rate=annual_rate,
            months=months,
        ).amount

    policy_limits = PolicyLimits(ltv_limit_amount=ltv.amount)
    # registry는 기본값이 있는 필수 인자라 None을 넘기면 안 된다.
    routing_kwargs = {"registry": registry} if registry is not None else {}
    routing = route_product_candidates(
        list(candidates),
        user_facts=request.user_facts,
        as_of=request.as_of,
        **routing_kwargs,  # type: ignore[arg-type]
    )

    executable: list[LoanComputation] = []
    not_executable: list[LoanComputation] = []
    unresolved: list[LoanOptionAdaptation] = []
    rejected: list[LoanOptionAdaptation] = []

    stress_sources: list[str] = []

    for handoff in (*routing.forwardable, *routing.rejected, *routing.needs_review):
        stress = _resolve_stress_rate(handoff, request)

        # 자격 판정에서 이미 탈락한 상품은 스트레스 금리가 없어도 그대로 넘긴다 —
        # 탈락 사유를 "입력 부족"으로 바꿔 버리면 이유가 흐려진다.
        if stress is None and handoff.status is EvaluationStatus.PASS:
            unresolved.append(
                LoanOptionAdaptation(
                    product_name=handoff.product.product_name,
                    option=None,
                    status=EvaluationStatus.UNKNOWN,
                    missing_inputs=("stress_dsr_rate",),
                    reasons=(
                        "스트레스 DSR 가산금리를 확정하지 못했습니다. "
                        "적용하지 않고 계산하면 한도가 과대평가됩니다.",
                    ),
                )
            )
            continue

        if stress is not None and stress.source not in stress_sources:
            stress_sources.append(stress.source)

        for adaptation in adapt_handoff_for_loan_max(
            handoff,
            borrower=request.borrower,
            policy_limits=policy_limits,
            required_amount=request.required_amount,
            months=request.months,
            rate_selection=request.rate_selection,
            dti_limit_resolver=resolve_dti,
            dsr_rate_add_on=None if stress is None else stress.rate,
        ):
            if adaptation.status is EvaluationStatus.FAIL:
                rejected.append(adaptation)
            elif adaptation.status is EvaluationStatus.UNKNOWN:
                unresolved.append(adaptation)
            else:
                computation = compute_loan_option(adaptation)
                target = executable if computation.is_executable else not_executable
                target.append(computation)

    return LoanSimulationResult(
        executable=tuple(executable),
        not_executable=tuple(not_executable),
        unresolved=tuple(unresolved),
        rejected=tuple(rejected),
        ltv=ltv,
        policy_as_of=request.as_of,
        policy_sources=sources + tuple(stress_sources),
        notes=_regulation_notes(ltv, dti_ratio, request),
    )


# Rule Pack 카테고리 → 스트레스 금리 구분. 주담대만 지역별로 다르고 나머지는
# "주담대 외" 한 묶음이지만, 신용대출은 잔액 조건이 붙어 따로 둔다.
_STRESS_KIND_BY_CATEGORY: dict[ProductCategory, StressLoanKind] = {
    ProductCategory.MORTGAGE_LOAN: StressLoanKind.MORTGAGE,
    ProductCategory.CREDIT_LOAN: StressLoanKind.CREDIT,
    ProductCategory.JEONSE_LOAN: StressLoanKind.OTHER,
}


def _resolve_stress_rate(
    handoff: ProductEngineHandoff,
    request: LoanSimulationRequest,
) -> StressRate | None:
    """이 상품에 적용할 스트레스 DSR 가산금리를 찾는다.

    확정하지 못하면 None이며, 호출부는 0으로 대체하지 않고 계산을 포기한다 —
    스트레스를 빠뜨리면 한도가 **과대**평가되기 때문이다. 다른 결측들이 과소평가
    방향이라 보수적 하한으로 처리되는 것과 반대다.
    """
    kind = _STRESS_KIND_BY_CATEGORY.get(handoff.rule_result.category)
    if kind is None:
        return None
    return get_stress_rate(
        resolve_stress_region(
            is_capital_region=request.is_capital_region,
            is_regulated_region=request.zone is not RegulationZone.NON_REGULATED,
        ),
        kind,
        as_of=request.as_of,
        credit_loan_balance=request.credit_loan_balance,
        allow_unverified=request.allow_unverified_regulation,
    )


def _regulation_notes(
    ltv: ResolvedPolicyLimit,
    dti_ratio: object | None,
    request: LoanSimulationRequest,
) -> tuple[str, ...]:
    """결과에 함께 표시할 정책 근거. 어떤 기준으로 계산했는지 밝힌다."""
    notes: list[str] = [f"규제 기준일 {request.as_of.isoformat()}"]
    if ltv.binding_reason is not None:
        notes.append(f"LTV 산출: {ltv.binding_reason}")
    if ltv.note is not None:
        notes.append(ltv.note)
    if dti_ratio is None:
        notes.append(f"DTI 비율을 찾을 수 없는 지역 구분입니다: {request.dti_region}")
    if request.allow_unverified_regulation:
        notes.append("미검증 규제값 사용을 허용한 결과입니다 — 대외 표기 전 출처를 확인하세요.")
    notes.append(
        f"차주단위 DSR 규제 상한 {BANK_DSR_LIMIT.ratio * 100:.0f}% "
        f"(적용된 안전기준 {request.borrower.safe_dsr * 100:.0f}%는 서비스 내부 기준)"
    )
    return tuple(notes)


def summarize(result: LoanSimulationResult) -> Sequence[str]:
    """사람이 읽을 한 줄 요약들. 디버깅·리포트 초안용."""
    if not result.is_resolved:
        return (f"규제 한도를 확정하지 못했습니다: {', '.join(result.missing_inputs)}",)

    lines = [
        f"계산 가능 {len(result.executable)}건 / "
        f"최소금액 미달 {len(result.not_executable)}건 / "
        f"입력 부족 {len(result.unresolved)}건 / "
        f"자격 탈락 {len(result.rejected)}건"
    ]
    for computation in sorted(result.executable, key=lambda c: c.amount, reverse=True):
        note = f"  ※ {computation.assumptions[0]}" if computation.assumptions else ""
        lines.append(f"{computation.product_name}: {computation.amount:,.0f}원{note}")
    return tuple(lines)
