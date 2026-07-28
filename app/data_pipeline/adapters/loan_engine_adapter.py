from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from app.data_pipeline.curated.loan_limits import (
    LimitKind,
    ResolvedProductLimit,
    resolve_product_limit,
)
from app.data_pipeline.normalizers.loan_product import (
    NormalizedLoanOption,
    normalize_loan_product,
)
from app.engines.loan.formulas import buffer, loan_max
from app.rule_engine.product_packs.handoff import ProductEngineHandoff
from app.rule_engine.product_packs.models import EvaluationStatus

# Rule Pack 판정(`route_product_candidates()`)을 통과한 대출 상품을 대출 계산
# 엔진(`formulas.loan_max()`)의 입력으로 조립한다. product_packs/README.md의
# "대출 엔진은 forwardable의 옵션별 한도·금리·상환방식을 계산한다"에 해당하는
# 연결 계층이다.
#
# 이 어댑터는 Rule Pack과 같은 규율을 따른다 — **모르면 UNKNOWN을 반환하고
# 절대 임의값으로 채우지 않는다.** loan_max()가 요구하는 값 중 원천 상품
# 데이터에 아예 없는 것들이 있기 때문이다(부록 B-5):
#
#   - LTV·DTI 한도 금액: 상품별 데이터가 아니라 규제 상수표 소관이다. 호출자가
#     `app/regulations/mortgage_limits.py`로 구해 `PolicyLimits`에 담아 넘긴다.
#   - 상품별 대출한도: baseList.loan_lmt 자유텍스트에서 확정되지 않으면 None.
#     이 경우 검수된 한도표(curated/loan_limits.py)를 차주 facts와 함께 조회한다.
#   - 기존 대출 연 상환액: 마이데이터에서 계산되는 값이라
#     `BorrowerFinancialState`로 받는다(engines/loan/existing_debt.py 소관).


# (연이율, 개월수) -> DTI 한도 금액. 확정할 수 없으면 None.
DtiLimitResolver = Callable[[Decimal, int], Decimal | None]


@dataclass(frozen=True)
class BorrowerFinancialState:
    """대출 가능액 계산에 필요한 차주 재무 상태(부록 A-2 입력).

    금액은 원, `safe_dsr`는 비율(0~1)이다. `safe_dsr`은 법정 상한이 아니라
    서비스 내부 안전기준이므로(§3, §14.1) 결과에 "내부 추천 기준"으로 표기한다.
    """

    annual_income: Decimal
    existing_annual_debt_service: Decimal
    post_purchase_monthly_income: Decimal
    post_purchase_monthly_expense: Decimal
    other_existing_monthly_debt_service: Decimal
    monthly_essential_expense: Decimal
    safe_dsr: Decimal
    # 기존 대출의 연간 **이자만**. DTI 분자는 기타 대출을 이자만 세는 반면
    # `existing_annual_debt_service`(DSR용)는 원금까지 센다. 두 값을 뭉치면
    # DTI 계산이 틀리므로 따로 받는다. 없으면 DSR용 값으로 대체하는데, 더 많이
    # 빼는 셈이라 DTI 한도를 낮게 잡는다(과소평가 = 안전).
    existing_annual_interest: Decimal | None = None

    @property
    def dti_other_annual_interest(self) -> Decimal:
        """DTI 분자에 넣을 기타 부채 연 이자."""
        if self.existing_annual_interest is not None:
            return self.existing_annual_interest
        return self.existing_annual_debt_service

    @property
    def buffer_target(self) -> Decimal:
        """부록 A-8 Buffer = max(300,000원, 필수생활비 × 0.10)."""
        return buffer(self.monthly_essential_expense)


@dataclass(frozen=True)
class PolicyLimits:
    """LTV·DTI 법정 한도를 **금액으로 환산한** 값(§9.1, 부록 A-2).

    비율(LTV 70% 등)이 아니라 금액이다 — 비율→금액 환산은 주택가격·규제지역에
    따라 달라지므로 `loan_max()`의 책임이 아니며(formulas.py 주석) 이 어댑터의
    책임도 아니다. 호출자가 기준일·출처와 함께 구해서 넘긴다(§20, 부록 B-5).

    LTV는 주택가격만으로 정해지므로 옵션과 무관하게 하나면 된다. 반면 **DTI는
    옵션마다 다르다** — DTI 상한은 연 원리금 기준이고 거기서 원금을 역산하려면
    금리와 만기가 필요한데, 그 둘이 옵션별로 다르기 때문이다. 그래서 고정
    금액(`dti_limit_amount`) 대신 옵션별 환산 함수를 넘기는 쪽이 정확하다
    (`adapt_handoff_for_loan_max(dti_limit_resolver=...)`).
    """

    ltv_limit_amount: Decimal
    dti_limit_amount: Decimal | None = None


@dataclass(frozen=True)
class LoanMaxInputs:
    """`loan_max()`에 그대로 넘길 수 있는, 빠짐없이 채워진 입력."""

    ltv_limit_amount: Decimal
    product_limit_amount: Decimal
    dti_limit_amount: Decimal
    required_amount: Decimal
    annual_rate: Decimal
    months: int
    existing_annual_debt_service: Decimal
    annual_income: Decimal
    safe_dsr: Decimal
    post_purchase_monthly_income: Decimal
    post_purchase_monthly_expense: Decimal
    other_existing_monthly_debt_service: Decimal
    buffer_target: Decimal
    # DSR 판정에만 쓰는 심사 금리(스트레스 DSR). None이면 실제 금리로 판정하며,
    # 그때는 스트레스가 미적용이므로 한도가 과대평가된다.
    dsr_annual_rate: Decimal | None = None

    def as_kwargs(self) -> dict[str, object]:
        return {
            "ltv_limit_amount": self.ltv_limit_amount,
            "product_limit_amount": self.product_limit_amount,
            "dti_limit_amount": self.dti_limit_amount,
            "required_amount": self.required_amount,
            "annual_rate": self.annual_rate,
            "months": self.months,
            "dsr_annual_rate": self.dsr_annual_rate,
            "existing_annual_debt_service": self.existing_annual_debt_service,
            "annual_income": self.annual_income,
            "safe_dsr": self.safe_dsr,
            "post_purchase_monthly_income": self.post_purchase_monthly_income,
            "post_purchase_monthly_expense": self.post_purchase_monthly_expense,
            "other_existing_monthly_debt_service": self.other_existing_monthly_debt_service,
            "buffer_target": self.buffer_target,
        }


@dataclass(frozen=True)
class LoanOptionAdaptation:
    """옵션 하나에 대한 어댑터 결과.

    `status`는 Rule Pack과 같은 3진 값을 쓴다:
    - PASS: `inputs`가 채워져 있어 `loan_max()`를 바로 호출할 수 있다.
    - UNKNOWN: 값이 부족해 계산할 수 없다. `missing_inputs`에 무엇이 없는지 담는다.
    - FAIL: 가입 필수조건 미충족(Rule Pack 판정 결과를 그대로 전달).
    """

    product_name: str
    option: NormalizedLoanOption | None
    status: EvaluationStatus
    inputs: LoanMaxInputs | None = None
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    # 상품 한도를 확정하지 못해 더 낮은 값을 가정했다면 그 내역. 비어 있지 않은
    # PASS는 "계산은 됐지만 과소평가일 수 있다"는 뜻이므로 결과에 함께 표시한다.
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    # 상품 최소 실행금액(있는 경우). `loan_max()` 입력이 아니라 계산 **결과**를
    # 판정하는 데 쓰므로 `LoanMaxInputs`가 아니라 여기에 싣는다.
    product_minimum_amount: Decimal | None = None


def adapt_handoff_for_loan_max(
    handoff: ProductEngineHandoff,
    *,
    borrower: BorrowerFinancialState,
    policy_limits: PolicyLimits,
    required_amount: Decimal,
    months: int,
    rate_selection: str = "avg",
    dti_limit_resolver: DtiLimitResolver | None = None,
    dsr_rate_add_on: Decimal | None = None,
) -> tuple[LoanOptionAdaptation, ...]:
    """PASS 판정된 대출 상품 하나를 옵션별 `loan_max()` 입력으로 변환한다.

    옵션(담보유형·상환방식·금리유형 조합)마다 금리가 다르므로 결과도 옵션 수만큼
    나온다. 판정이 PASS가 아니면 계산을 시도하지 않고 그 상태를 그대로 돌려준다 —
    자격 판정은 Rule Pack의 책임이고 어댑터가 뒤집지 않는다(§13.1).

    `dti_limit_resolver`를 넘기면 DTI 한도를 옵션의 금리·만기로 매번 환산한다.
    넘기지 않으면 `policy_limits.dti_limit_amount`를 모든 옵션에 공통으로 쓰는데,
    이는 옵션 금리가 서로 다를 때 틀린 값이 된다. 규제 모듈을 여기서 직접 부르지
    않고 함수로 받는 이유는, 이 어댑터가 규제표를 모르도록 유지하기 위해서다.

    `dsr_rate_add_on`은 스트레스 DSR 가산금리다. 주면 DSR 판정에만 실제 금리에
    더해 쓰고, 월 현금흐름 판정에는 실제 금리를 그대로 쓴다. **주지 않으면
    스트레스를 적용하지 않으므로 한도가 과대평가된다** — 호출자가 규제표
    (`app/regulations/stress_dsr.py`)에서 구해 넘기고, 구하지 못하면 계산을
    포기하는 쪽이 맞다.
    """
    product_name = handoff.product.product_name

    if handoff.status is not EvaluationStatus.PASS:
        return (
            LoanOptionAdaptation(
                product_name=product_name,
                option=None,
                status=handoff.status,
                reasons=_rule_reasons(handoff),
            ),
        )

    product = normalize_loan_product(handoff.product.base_data, handoff.product.option_list)

    if not product.options:
        return (
            LoanOptionAdaptation(
                product_name=product_name,
                option=None,
                status=EvaluationStatus.UNKNOWN,
                missing_inputs=("annual_rate",),
                reasons=("금리를 확정할 수 있는 optionList 행이 없습니다.",),
            ),
        )

    limit = _resolve_limit_amount(
        product_name,
        parsed_limit=product.max_loan_amount,
        facts=handoff.user_facts,
        required_amount=required_amount,
    )

    return tuple(
        _adapt_option(
            option,
            product_name=product_name,
            limit=limit,
            borrower=borrower,
            policy_limits=policy_limits,
            required_amount=required_amount,
            months=months,
            rate_selection=rate_selection,
            dti_limit_resolver=dti_limit_resolver,
            dsr_rate_add_on=dsr_rate_add_on,
        )
        for option in product.options
    )


def _resolve_limit_amount(
    product_name: str,
    *,
    parsed_limit: Decimal | None,
    facts: Mapping[str, object],
    required_amount: Decimal,
) -> ResolvedProductLimit:
    """상품 한도를 확정한다 — 검수된 한도표가 우선, 정규식 파서가 차선.

    한도표를 먼저 보는 이유는 원문이 조건부 문구인 경우 파서가 구조적으로
    답할 수 없기 때문이다(curated/loan_limits.py 상단 주석). 파서 값은 한도표에
    아직 없는 상품을 위한 안전망으로만 남긴다.

    `UNCAPPED`(상품 고유 상한 없음)는 `required_amount`로 환산한다. `loan_max()`의
    탐색 상한이 `min(각 한도, required_amount)`이므로, 요청액과 같은 값을 넣으면
    이 항목은 구속하지 않는 상태가 되어 LTV·DTI·DSR만 남는다.
    """
    resolved = resolve_product_limit(product_name, facts)
    if resolved.kind is LimitKind.AMOUNT:
        return resolved
    if resolved.kind is LimitKind.UNCAPPED:
        return ResolvedProductLimit(
            kind=LimitKind.AMOUNT,
            amount=required_amount,
            assumptions=resolved.assumptions,
            note=resolved.note,
            minimum_amount=resolved.minimum_amount,
        )
    if parsed_limit is not None:
        return ResolvedProductLimit(
            kind=LimitKind.AMOUNT,
            amount=parsed_limit,
            note="loan_lmt 원문에서 파싱한 단일 한도",
            minimum_amount=resolved.minimum_amount,
        )
    return resolved


def _adapt_option(
    option: NormalizedLoanOption,
    *,
    product_name: str,
    limit: ResolvedProductLimit,
    borrower: BorrowerFinancialState,
    policy_limits: PolicyLimits,
    required_amount: Decimal,
    months: int,
    rate_selection: str,
    dti_limit_resolver: DtiLimitResolver | None = None,
    dsr_rate_add_on: Decimal | None = None,
) -> LoanOptionAdaptation:
    if limit.kind is not LimitKind.AMOUNT or limit.amount is None:
        return LoanOptionAdaptation(
            product_name=product_name,
            option=option,
            status=EvaluationStatus.UNKNOWN,
            missing_inputs=("product_limit_amount", *limit.missing_facts),
            reasons=(limit.note or "상품 한도를 확정하지 못했습니다.",),
        )

    annual_rate = option.rate(rate_selection)

    # DTI 한도는 이 옵션의 금리·만기로 환산해야 한다. 환산기가 없으면 옵션
    # 공통값으로 물러서지만, 그 값조차 없으면 임의로 채우지 않고 UNKNOWN이다.
    if dti_limit_resolver is not None:
        dti_limit_amount = dti_limit_resolver(annual_rate, months)
    else:
        dti_limit_amount = policy_limits.dti_limit_amount

    if dti_limit_amount is None:
        return LoanOptionAdaptation(
            product_name=product_name,
            option=option,
            status=EvaluationStatus.UNKNOWN,
            missing_inputs=("dti_limit_amount",),
            reasons=("DTI 한도를 확정하지 못했습니다.",),
        )

    return LoanOptionAdaptation(
        product_name=product_name,
        option=option,
        status=EvaluationStatus.PASS,
        assumptions=limit.assumptions,
        product_minimum_amount=limit.minimum_amount,
        inputs=LoanMaxInputs(
            ltv_limit_amount=policy_limits.ltv_limit_amount,
            product_limit_amount=limit.amount,
            dti_limit_amount=dti_limit_amount,
            required_amount=required_amount,
            annual_rate=annual_rate,
            dsr_annual_rate=(
                None if dsr_rate_add_on is None else annual_rate + dsr_rate_add_on
            ),
            months=months,
            existing_annual_debt_service=borrower.existing_annual_debt_service,
            annual_income=borrower.annual_income,
            safe_dsr=borrower.safe_dsr,
            post_purchase_monthly_income=borrower.post_purchase_monthly_income,
            post_purchase_monthly_expense=borrower.post_purchase_monthly_expense,
            other_existing_monthly_debt_service=borrower.other_existing_monthly_debt_service,
            buffer_target=borrower.buffer_target,
        ),
    )


@dataclass(frozen=True)
class LoanComputation:
    """대출 가능액 계산 결과와 그 실행 가능 여부.

    `status`는 계산된 금액을 실제로 빌릴 수 있는지를 뜻한다:
    - PASS: 실행 가능.
    - FAIL: 금액은 계산됐지만 상품 최소 실행금액에 미달해 실행할 수 없다.

    금액을 최소금액까지 끌어올리는 선택지는 없다 — 그렇게 하면 애초에 금액을
    낮춘 DSR·LTV·현금흐름 제약을 위반하게 되므로 상품을 제외하는 것이 맞다.
    """

    product_name: str
    option: NormalizedLoanOption | None
    status: EvaluationStatus
    amount: Decimal
    product_minimum_amount: Decimal | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_executable(self) -> bool:
        return self.status is EvaluationStatus.PASS


def compute_loan_max(adaptation: LoanOptionAdaptation) -> Decimal:
    """PASS 상태의 어댑터 결과로 대출 가능액을 계산한다(부록 A-2).

    PASS가 아닌 결과를 넘기면 `ValueError`다 — UNKNOWN을 0원으로 뭉개면
    "한도가 0"과 "한도를 모름"이 구분되지 않기 때문이다.

    이 함수는 금액만 돌려주며 **상품 최소 실행금액을 판정하지 않는다.** 상품
    비교 결과를 만들 때는 `compute_loan_option()`을 쓸 것.
    """
    if adaptation.status is not EvaluationStatus.PASS or adaptation.inputs is None:
        raise ValueError(
            f"{adaptation.product_name}: 계산에 필요한 입력이 확정되지 않았습니다 "
            f"(status={adaptation.status}, missing={adaptation.missing_inputs})."
        )
    return loan_max(**adaptation.inputs.as_kwargs())  # type: ignore[arg-type]


def compute_loan_option(adaptation: LoanOptionAdaptation) -> LoanComputation:
    """대출 가능액을 계산하고 상품 최소 실행금액까지 판정한다.

    Rule Pack은 **요청금액**이 최소금액 이상인지만 본다. 그런데 소득·DSR·현금흐름
    때문에 계산 결과가 요청금액보다 작아질 수 있고, 그 결과가 최소금액에 미달하면
    판정은 PASS인데 실제로는 실행할 수 없는 상품이 된다. 그 구멍을 여기서 막는다.
    """
    amount = compute_loan_max(adaptation)
    minimum = adaptation.product_minimum_amount

    if minimum is not None and amount < minimum:
        return LoanComputation(
            product_name=adaptation.product_name,
            option=adaptation.option,
            status=EvaluationStatus.FAIL,
            amount=amount,
            product_minimum_amount=minimum,
            assumptions=adaptation.assumptions,
            reasons=(
                f"계산된 대출가능액 {amount:,.0f}원이 상품 최소 실행금액 "
                f"{minimum:,.0f}원보다 작습니다.",
            ),
        )

    return LoanComputation(
        product_name=adaptation.product_name,
        option=adaptation.option,
        status=EvaluationStatus.PASS,
        amount=amount,
        product_minimum_amount=minimum,
        assumptions=adaptation.assumptions,
    )


def _rule_reasons(handoff: ProductEngineHandoff) -> tuple[str, ...]:
    reasons: list[str] = []
    for decision in handoff.rule_result.decisions:
        if decision.status is EvaluationStatus.PASS:
            continue
        reasons.extend(decision.reasons)
    return tuple(reasons)


def adapt_raw_product_for_loan_max(
    base_data: Mapping[str, object],
    option_list: tuple[Mapping[str, object], ...],
) -> tuple[Decimal | None, tuple[NormalizedLoanOption, ...]]:
    """Rule Pack 없이 원천 상품 데이터만 정규화하고 싶을 때 쓰는 보조 함수."""
    product = normalize_loan_product(base_data, option_list)
    return product.max_loan_amount, product.options
