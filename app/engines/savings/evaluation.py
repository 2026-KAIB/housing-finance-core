import calendar
from datetime import date
from decimal import Decimal, localcontext

from app.engines.savings.models import (
    SavingsEvaluationInput,
    SavingsEvaluationResult,
    SavingsEvaluationStatus,
    SavingsScoreComponents,
)

_RATE_WEIGHT = Decimal("0.30")
_MATURITY_WEIGHT = Decimal("0.25")
_LIQUIDITY_WEIGHT = Decimal("0.20")
_SAFETY_WEIGHT = Decimal("0.15")
_BONUS_WEIGHT = Decimal("0.10")


def _require_score(value: Decimal, name: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{name}은(는) 0 이상 1 이하의 점수여야 합니다.")


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def add_months(start: date, months: int) -> date:
    """월말을 보정해 상품 만기일을 계산한다."""
    if months <= 0:
        raise ValueError("months은(는) 0보다 커야 합니다.")
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _normalized_rate_score(
    rate: Decimal,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    _require_non_negative(rate, "rate")
    _require_non_negative(minimum, "market_min_rate")
    _require_non_negative(maximum, "market_max_rate")
    if maximum < minimum:
        raise ValueError("market_max_rate은(는) market_min_rate보다 작을 수 없습니다.")
    if maximum == minimum:
        return Decimal(1)
    return min(Decimal(1), max(Decimal(0), (rate - minimum) / (maximum - minimum)))


def _maturity_fit_score(
    maturity_date: date,
    fund_needed_date: date,
    tolerance_days: int,
) -> Decimal:
    if tolerance_days <= 0:
        raise ValueError("maturity_tolerance_days은(는) 0보다 커야 합니다.")
    distance = abs((fund_needed_date - maturity_date).days)
    with localcontext() as context:
        context.prec = 40
        return (-Decimal(distance) / Decimal(tolerance_days)).exp()


def evaluate_savings_option(payload: SavingsEvaluationInput) -> SavingsEvaluationResult:
    """설계 §11의 주택구매자금용 상품점수를 계산한다.

    상품별 가입조건은 앞선 Product Rule Pack이 담당한다. 여기서는 계산 결과에
    공통 목표일·위험·예금자보호 조건을 적용하고, 통과한 옵션만 점수화한다.
    """
    _require_score(payload.liquidity_score, "liquidity_score")
    _require_non_negative(
        payload.existing_institution_deposit,
        "existing_institution_deposit",
    )
    _require_non_negative(payload.deposit_protection_limit, "deposit_protection_limit")

    maturity_date = add_months(payload.as_of, payload.calculation.term_months)
    projected_deposit = (
        payload.existing_institution_deposit + payload.calculation.maturity_amount
    )
    reasons: list[str] = []

    if maturity_date > payload.fund_needed_date:
        reasons.append(
            f"상품 만기({maturity_date.isoformat()})가 자금 필요시점"
            f"({payload.fund_needed_date.isoformat()})보다 늦습니다."
        )
    if not payload.is_principal_protected and not payload.accepts_principal_risk:
        reasons.append("원금손실 가능 상품이며 사용자의 위험성향과 맞지 않습니다.")
    # 예산 전액을 넣으면 한도를 넘는다는 것은 **부적격이 아니다.** 넘지 않는
    # 만큼만 넣으면 되고, 실제 상한 절단은 포트폴리오 배분이 기관 단위로 한다
    # (``portfolio._institution_capacity``). 여기서 상품을 통째로 버리면 "일부
    # 가능"이 "전부 불가"로 뭉개진다 — 실제로 목돈 1.5억 사용자에게 예금이 한 건도
    # 추천되지 않고 1.39억이 통째로 미배분으로 남았다. 보호 한도 안에서 예치할 수
    # 있는 9,600만원까지 놀리는 것은 보수적인 답이 아니라 틀린 답이다.
    #
    # 정말로 넣을 수 없는 경우는 **기존 예치액만으로 이미 한도가 찬** 때다. 그때는
    # 보호받으며 추가로 넣을 수 있는 금액이 0원이라 절단할 여지가 없다.
    if (
        payload.is_deposit_protected
        and payload.existing_institution_deposit >= payload.deposit_protection_limit
    ):
        reasons.append(
            f"동일 금융회사 기존 예치액 {payload.existing_institution_deposit}원이"
            f" 예금자보호 한도 {payload.deposit_protection_limit}원 이상이어서"
            " 보호받으며 추가로 예치할 수 있는 금액이 없습니다."
        )

    if reasons:
        return SavingsEvaluationResult(
            product_name=payload.calculation.product_name,
            term_months=payload.calculation.term_months,
            maturity_date=maturity_date,
            projected_institution_deposit=projected_deposit,
            status=SavingsEvaluationStatus.INELIGIBLE,
            reasons=tuple(reasons),
        )

    rate_score = _normalized_rate_score(
        payload.calculation.annualized_net_return_rate,
        minimum=payload.market_min_rate,
        maximum=payload.market_max_rate,
    )
    maturity_score = _maturity_fit_score(
        maturity_date,
        payload.fund_needed_date,
        payload.maturity_tolerance_days,
    )
    principal_score = Decimal(1) if payload.is_principal_protected else Decimal(0)
    protection_score = Decimal(1) if payload.is_deposit_protected else Decimal(0)
    safety_score = (principal_score + protection_score) / Decimal(2)
    bonus_score = payload.calculation.bonus_achievement_probability
    _require_score(bonus_score, "bonus_achievement_probability")

    components = SavingsScoreComponents(
        rate_score=rate_score,
        maturity_fit_score=maturity_score,
        liquidity_score=payload.liquidity_score,
        safety_score=safety_score,
        bonus_achievement_score=bonus_score,
    )
    score = Decimal(100) * (
        _RATE_WEIGHT * components.rate_score
        + _MATURITY_WEIGHT * components.maturity_fit_score
        + _LIQUIDITY_WEIGHT * components.liquidity_score
        + _SAFETY_WEIGHT * components.safety_score
        + _BONUS_WEIGHT * components.bonus_achievement_score
    )

    return SavingsEvaluationResult(
        product_name=payload.calculation.product_name,
        term_months=payload.calculation.term_months,
        maturity_date=maturity_date,
        projected_institution_deposit=projected_deposit,
        status=SavingsEvaluationStatus.ELIGIBLE,
        score=score,
        components=components,
    )
