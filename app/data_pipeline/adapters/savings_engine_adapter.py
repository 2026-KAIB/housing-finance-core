from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.data_pipeline.normalizers.savings_product import (
    NormalizedSavingsOption,
    normalize_savings_product,
)
from app.engines.savings.calculator import calculate_savings
from app.engines.savings.models import (
    ContributionTiming,
    SavingsCalculationInput,
    SavingsCalculationResult,
    SavingsProductKind,
)
from app.rule_engine.product_packs.handoff import ProductEngineHandoff
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductCategory,
)


@dataclass(frozen=True)
class SavingsCalculationPolicy:
    """원천 상품에 없어서 계산 호출자가 명시해야 하는 가정."""

    tax_rate: Decimal
    bonus_achievement_probability: Decimal | None = None
    contribution_timing: ContributionTiming | None = None

    def __post_init__(self) -> None:
        if self.tax_rate < 0 or self.tax_rate > 1:
            raise ValueError("tax_rate은(는) 0 이상 1 이하의 비율이어야 합니다.")
        probability = self.bonus_achievement_probability
        if probability is not None and (probability < 0 or probability > 1):
            raise ValueError(
                "bonus_achievement_probability은(는) 0 이상 1 이하의 비율이어야 합니다."
            )
        if (
            self.contribution_timing is not None
            and not isinstance(self.contribution_timing, ContributionTiming)
        ):
            raise ValueError("contribution_timing은 ContributionTiming 값이어야 합니다.")


@dataclass(frozen=True)
class SavingsOptionAdaptation:
    """Rule Pack 결과와 옵션 하나를 순수 계산기 입력으로 바꾼 결과."""

    product_name: str
    option: NormalizedSavingsOption | None
    status: EvaluationStatus
    inputs: SavingsCalculationInput | None = None
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _product_kind(category: ProductCategory) -> SavingsProductKind:
    if category is ProductCategory.TERM_DEPOSIT:
        return SavingsProductKind.TERM_DEPOSIT
    if category is ProductCategory.INSTALLMENT_SAVINGS:
        return SavingsProductKind.INSTALLMENT_SAVINGS
    raise ValueError(f"예적금 어댑터가 처리할 수 없는 상품 분류입니다: {category}")


def _positive_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}은(는) 금액 숫자여야 합니다.")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name}은(는) 금액 숫자여야 합니다.") from error
    if not converted.is_finite() or converted <= 0:
        raise ValueError(f"{field_name}은(는) 0보다 큰 유한한 금액이어야 합니다.")
    return converted


def _rule_reasons(handoff: ProductEngineHandoff) -> tuple[str, ...]:
    return tuple(
        reason
        for decision in handoff.rule_result.decisions
        if decision.status is not EvaluationStatus.PASS
        for reason in decision.reasons
    )


def _amount(
    handoff: ProductEngineHandoff,
    product_kind: SavingsProductKind,
) -> tuple[str, Decimal | None, str | None]:
    field_name = (
        "deposit_amount"
        if product_kind is SavingsProductKind.TERM_DEPOSIT
        else "monthly_payment_amount"
    )
    value = handoff.user_facts.get(field_name)
    if value is None:
        return field_name, None, f"{field_name} 입력이 없습니다."
    try:
        return field_name, _positive_decimal(value, field_name), None
    except ValueError as error:
        return field_name, None, str(error)


def adapt_handoff_for_savings_calculation(
    handoff: ProductEngineHandoff,
    *,
    policy: SavingsCalculationPolicy,
) -> tuple[SavingsOptionAdaptation, ...]:
    """Rule Pack handoff를 옵션별 ``SavingsCalculationInput``으로 변환한다.

    가입조건 판정은 Rule Pack 결과를 그대로 보존한다. DB 원천 필드의 단위 변환은
    normalizer에 맡기고, 이 계층은 사용자 금액과 호출자 정책을 결합하는 일만 한다.
    """

    product_name = handoff.product.product_name
    product_kind = _product_kind(handoff.rule_result.category)

    if handoff.status is not EvaluationStatus.PASS:
        return (
            SavingsOptionAdaptation(
                product_name=product_name,
                option=None,
                status=handoff.status,
                reasons=_rule_reasons(handoff),
            ),
        )

    amount_field, amount, amount_error = _amount(handoff, product_kind)
    if amount is None:
        return (
            SavingsOptionAdaptation(
                product_name=product_name,
                option=None,
                status=EvaluationStatus.UNKNOWN,
                missing_inputs=(amount_field,),
                reasons=(amount_error or f"{amount_field}을(를) 확인할 수 없습니다.",),
            ),
        )

    if (
        product_kind is SavingsProductKind.INSTALLMENT_SAVINGS
        and policy.contribution_timing is None
    ):
        return (
            SavingsOptionAdaptation(
                product_name=product_name,
                option=None,
                status=EvaluationStatus.UNKNOWN,
                missing_inputs=("contribution_timing",),
                reasons=("적금 납입 시점 가정이 필요합니다.",),
            ),
        )

    product = normalize_savings_product(
        handoff.product.base_data,
        handoff.product.option_list,
        product_kind=product_kind,
    )
    adaptations: list[SavingsOptionAdaptation] = []

    if product.extra_rate_info is not None:
        adaptations.append(
            SavingsOptionAdaptation(
                product_name=product_name,
                option=None,
                status=EvaluationStatus.UNKNOWN,
                missing_inputs=("extra_rate_info_calculation_policy",),
                reasons=(
                    "표준 금리 옵션 밖의 extra_rate_info 계산 방식은 아직 "
                    "구조화되지 않았습니다.",
                ),
            )
        )

    for issue in product.issues:
        adaptations.append(
            SavingsOptionAdaptation(
                product_name=product_name,
                option=None,
                status=EvaluationStatus.UNKNOWN,
                missing_inputs=issue.missing_or_invalid_fields or ("savings_option",),
                reasons=(f"금리 옵션 {issue.option_index}: {issue.reason}",),
            )
        )

    for option in product.options:
        probability = policy.bonus_achievement_probability
        if option.annual_max_rate == option.annual_base_rate:
            probability = Decimal(0)
        if probability is None:
            adaptations.append(
                SavingsOptionAdaptation(
                    product_name=product_name,
                    option=option,
                    status=EvaluationStatus.UNKNOWN,
                    missing_inputs=("bonus_achievement_probability",),
                    reasons=(
                        "기본금리와 최고금리가 달라 우대조건 달성확률이 필요합니다.",
                    ),
                )
            )
            continue

        adaptations.append(
            SavingsOptionAdaptation(
                product_name=product_name,
                option=option,
                status=EvaluationStatus.PASS,
                inputs=SavingsCalculationInput(
                    product_name=product_name,
                    product_kind=product_kind,
                    term_months=option.term_months,
                    interest_type=option.interest_type,
                    annual_base_rate=option.annual_base_rate,
                    annual_max_rate=option.annual_max_rate,
                    bonus_achievement_probability=probability,
                    tax_rate=policy.tax_rate,
                    reserve_type_name=option.reserve_type_name,
                    deposit_amount=(
                        amount
                        if product_kind is SavingsProductKind.TERM_DEPOSIT
                        else None
                    ),
                    monthly_payment_amount=(
                        amount
                        if product_kind is SavingsProductKind.INSTALLMENT_SAVINGS
                        else None
                    ),
                    contribution_timing=(
                        policy.contribution_timing
                        if product_kind is SavingsProductKind.INSTALLMENT_SAVINGS
                        else None
                    ),
                ),
            )
        )

    if not adaptations:
        return (
            SavingsOptionAdaptation(
                product_name=product_name,
                option=None,
                status=EvaluationStatus.UNKNOWN,
                missing_inputs=("savings_rate_options",),
                reasons=("계산 가능한 예적금 금리 옵션이 없습니다.",),
            ),
        )
    return tuple(adaptations)


def compute_savings(
    adaptation: SavingsOptionAdaptation,
) -> SavingsCalculationResult:
    """PASS 어댑터 결과만 순수 예적금 계산기로 전달한다."""

    if adaptation.status is not EvaluationStatus.PASS or adaptation.inputs is None:
        raise ValueError(
            f"{adaptation.product_name}: 예적금 계산 입력이 확정되지 않았습니다."
            f"(status={adaptation.status}, missing={adaptation.missing_inputs})."
        )
    return calculate_savings(adaptation.inputs)
