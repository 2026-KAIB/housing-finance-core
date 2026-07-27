from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

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
#   - LTV·DTI 한도 금액: 상품별 데이터가 아니라 규제 상수표(policy/*.json) 소관.
#     저장소에 아직 그 표가 없으므로 호출자가 `PolicyLimits`로 명시해 넘긴다.
#   - 상품별 대출한도: baseList.loan_lmt 자유텍스트에서 확정되지 않으면 None.
#   - 기존 대출 연 상환액: 마이데이터에서 계산되는 값이라
#     `BorrowerFinancialState`로 받는다(engines/loan/existing_debt.py 소관).


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

    @property
    def buffer_target(self) -> Decimal:
        """부록 A-8 Buffer = max(300,000원, 필수생활비 × 0.10)."""
        return buffer(self.monthly_essential_expense)


@dataclass(frozen=True)
class PolicyLimits:
    """LTV·DTI 법정 한도를 **금액으로 환산한** 값(§9.1, 부록 A-2).

    비율(LTV 70% 등)이 아니라 금액이다 — 비율→금액 환산은 주택가격·규제지역에
    따라 달라지므로 `loan_max()`의 책임이 아니며(formulas.py 주석) 이 어댑터의
    책임도 아니다. 아직 `policy/*.json` 규제 상수표가 저장소에 없으므로
    호출자가 기준일·출처와 함께 구해서 넘겨야 한다(§20, 부록 B-5).
    """

    ltv_limit_amount: Decimal
    dti_limit_amount: Decimal


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

    def as_kwargs(self) -> dict[str, object]:
        return {
            "ltv_limit_amount": self.ltv_limit_amount,
            "product_limit_amount": self.product_limit_amount,
            "dti_limit_amount": self.dti_limit_amount,
            "required_amount": self.required_amount,
            "annual_rate": self.annual_rate,
            "months": self.months,
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


def adapt_handoff_for_loan_max(
    handoff: ProductEngineHandoff,
    *,
    borrower: BorrowerFinancialState,
    policy_limits: PolicyLimits,
    required_amount: Decimal,
    months: int,
    rate_selection: str = "avg",
) -> tuple[LoanOptionAdaptation, ...]:
    """PASS 판정된 대출 상품 하나를 옵션별 `loan_max()` 입력으로 변환한다.

    옵션(담보유형·상환방식·금리유형 조합)마다 금리가 다르므로 결과도 옵션 수만큼
    나온다. 판정이 PASS가 아니면 계산을 시도하지 않고 그 상태를 그대로 돌려준다 —
    자격 판정은 Rule Pack의 책임이고 어댑터가 뒤집지 않는다(§13.1).
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

    return tuple(
        _adapt_option(
            option,
            product_name=product_name,
            product_limit_amount=product.max_loan_amount,
            borrower=borrower,
            policy_limits=policy_limits,
            required_amount=required_amount,
            months=months,
            rate_selection=rate_selection,
        )
        for option in product.options
    )


def _adapt_option(
    option: NormalizedLoanOption,
    *,
    product_name: str,
    product_limit_amount: Decimal | None,
    borrower: BorrowerFinancialState,
    policy_limits: PolicyLimits,
    required_amount: Decimal,
    months: int,
    rate_selection: str,
) -> LoanOptionAdaptation:
    if product_limit_amount is None:
        return LoanOptionAdaptation(
            product_name=product_name,
            option=option,
            status=EvaluationStatus.UNKNOWN,
            missing_inputs=("product_limit_amount",),
            reasons=(
                "baseList.loan_lmt에서 상품 한도를 숫자로 확정하지 못했습니다 "
                "(조건부 한도가 섞여 있거나 담보조사가격 등에 의존).",
            ),
        )

    return LoanOptionAdaptation(
        product_name=product_name,
        option=option,
        status=EvaluationStatus.PASS,
        inputs=LoanMaxInputs(
            ltv_limit_amount=policy_limits.ltv_limit_amount,
            product_limit_amount=product_limit_amount,
            dti_limit_amount=policy_limits.dti_limit_amount,
            required_amount=required_amount,
            annual_rate=option.rate(rate_selection),
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


def compute_loan_max(adaptation: LoanOptionAdaptation) -> Decimal:
    """PASS 상태의 어댑터 결과로 대출 가능액을 계산한다(부록 A-2).

    PASS가 아닌 결과를 넘기면 `ValueError`다 — UNKNOWN을 0원으로 뭉개면
    "한도가 0"과 "한도를 모름"이 구분되지 않기 때문이다.
    """
    if adaptation.status is not EvaluationStatus.PASS or adaptation.inputs is None:
        raise ValueError(
            f"{adaptation.product_name}: 계산에 필요한 입력이 확정되지 않았습니다 "
            f"(status={adaptation.status}, missing={adaptation.missing_inputs})."
        )
    return loan_max(**adaptation.inputs.as_kwargs())  # type: ignore[arg-type]


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
