from decimal import Decimal, localcontext

from app.engines.savings.models import ContributionTiming, InterestType


def _require_positive(value: Decimal | int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name}은(는) 0보다 커야 합니다.")


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def _require_ratio(value: Decimal, name: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{name}은(는) 0 이상 1 이하의 비율이어야 합니다.")


def expected_annual_rate(
    *,
    annual_base_rate: Decimal,
    annual_max_rate: Decimal,
    bonus_achievement_probability: Decimal,
) -> Decimal:
    """기본금리와 최고금리 사이의 예상 적용금리를 계산한다(설계 §11.2).

    우대조건이 여러 개이거나 서로 종속된 상품은 상위 우대조건 평가 계층이 결합
    달성확률을 계산해 넘겨야 한다. 이 함수는 원문 조건을 해석하지 않는다.
    """
    _require_non_negative(annual_base_rate, "annual_base_rate")
    _require_non_negative(annual_max_rate, "annual_max_rate")
    _require_ratio(bonus_achievement_probability, "bonus_achievement_probability")
    if annual_max_rate < annual_base_rate:
        raise ValueError("annual_max_rate은(는) annual_base_rate보다 작을 수 없습니다.")
    return annual_base_rate + (
        annual_max_rate - annual_base_rate
    ) * bonus_achievement_probability


def monthly_effective_rate(annual_rate: Decimal) -> Decimal:
    """연 실효금리를 월 실효금리로 환산한다.

    대출의 명목환산 ``연이율 / 12``와 구분한다. 예적금 FV는
    ``(1 + 연이율) ** (1/12) - 1``을 사용한다.
    """
    _require_non_negative(annual_rate, "annual_rate")
    if annual_rate == 0:
        return Decimal("0")
    with localcontext() as context:
        context.prec = 40
        return ((Decimal(1) + annual_rate).ln() / Decimal(12)).exp() - Decimal(1)


def term_deposit_gross_maturity(
    *,
    principal: Decimal,
    annual_rate: Decimal,
    months: int,
    interest_type: InterestType,
) -> Decimal:
    """목돈 예금의 세전 만기금액."""
    _require_non_negative(principal, "principal")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(months, "months")

    if interest_type is InterestType.SIMPLE:
        return principal * (Decimal(1) + annual_rate * Decimal(months) / Decimal(12))
    if interest_type is InterestType.COMPOUND:
        monthly_rate = monthly_effective_rate(annual_rate)
        return principal * (Decimal(1) + monthly_rate) ** months
    raise ValueError(f"지원하지 않는 이자 계산 방식입니다: {interest_type!r}")


def installment_savings_gross_maturity(
    *,
    monthly_payment: Decimal,
    annual_rate: Decimal,
    months: int,
    interest_type: InterestType,
    contribution_timing: ContributionTiming,
) -> Decimal:
    """매월 동일 금액을 납입하는 적금의 세전 만기금액.

    단리는 각 회차 납입금이 실제 예치된 개월 수만큼만 이자를 받는다. 복리는
    설계 §10.1의 적립식 FV를 사용하고 월초 납입이면 한 달 성장분을 추가한다.
    """
    _require_non_negative(monthly_payment, "monthly_payment")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(months, "months")

    if interest_type is InterestType.SIMPLE:
        if contribution_timing is ContributionTiming.BEGINNING:
            earning_months = months * (months + 1) // 2
        elif contribution_timing is ContributionTiming.END:
            earning_months = months * (months - 1) // 2
        else:
            raise ValueError(f"지원하지 않는 납입 시점입니다: {contribution_timing!r}")
        interest = (
            monthly_payment
            * annual_rate
            * Decimal(earning_months)
            / Decimal(12)
        )
        return monthly_payment * Decimal(months) + interest

    if interest_type is InterestType.COMPOUND:
        monthly_rate = monthly_effective_rate(annual_rate)
        if monthly_rate == 0:
            return monthly_payment * Decimal(months)
        annuity = monthly_payment * (
            ((Decimal(1) + monthly_rate) ** months - Decimal(1)) / monthly_rate
        )
        if contribution_timing is ContributionTiming.BEGINNING:
            return annuity * (Decimal(1) + monthly_rate)
        if contribution_timing is ContributionTiming.END:
            return annuity
        raise ValueError(f"지원하지 않는 납입 시점입니다: {contribution_timing!r}")

    raise ValueError(f"지원하지 않는 이자 계산 방식입니다: {interest_type!r}")


def interest_tax(*, gross_interest: Decimal, tax_rate: Decimal) -> Decimal:
    """만기 이자에 적용할 세액.

    일반과세·비과세 여부는 이 함수가 결정하지 않고 호출자가 기준일 정책에 맞는
    세율을 명시한다.
    """
    _require_non_negative(gross_interest, "gross_interest")
    _require_ratio(tax_rate, "tax_rate")
    return gross_interest * tax_rate


def annualized_deposit_return(
    *,
    principal: Decimal,
    maturity_amount: Decimal,
    months: int,
) -> Decimal:
    """예금의 세후 만기금액을 기간 비교 가능한 연 실효수익률로 환산한다."""

    _require_positive(principal, "principal")
    _require_positive(maturity_amount, "maturity_amount")
    _require_positive(months, "months")
    with localcontext() as context:
        context.prec = 40
        growth = maturity_amount / principal
        return (growth.ln() * Decimal(12) / Decimal(months)).exp() - Decimal(1)


def _installment_future_value(
    *,
    monthly_payment: Decimal,
    monthly_rate: Decimal,
    months: int,
    contribution_timing: ContributionTiming,
) -> Decimal:
    if monthly_rate == 0:
        return monthly_payment * Decimal(months)
    annuity = monthly_payment * (
        ((Decimal(1) + monthly_rate) ** months - Decimal(1)) / monthly_rate
    )
    if contribution_timing is ContributionTiming.BEGINNING:
        return annuity * (Decimal(1) + monthly_rate)
    if contribution_timing is ContributionTiming.END:
        return annuity
    raise ValueError(f"지원하지 않는 납입 시점입니다: {contribution_timing!r}")


def annualized_installment_return(
    *,
    monthly_payment: Decimal,
    maturity_amount: Decimal,
    months: int,
    contribution_timing: ContributionTiming,
) -> Decimal:
    """적금의 세후 월 현금흐름 IRR을 연 실효수익률로 환산한다.

    단순히 ``순이자 / 납입원금``을 사용하면 긴 상품이 유리해진다. 동일 납입액의
    월 현금흐름과 세후 만기금액이 일치하는 월 수익률을 이분 탐색한 뒤 연환산한다.
    """

    _require_positive(monthly_payment, "monthly_payment")
    _require_positive(maturity_amount, "maturity_amount")
    _require_positive(months, "months")
    total_principal = monthly_payment * Decimal(months)
    if maturity_amount < total_principal:
        raise ValueError("maturity_amount은(는) 총 납입원금보다 작을 수 없습니다.")
    if maturity_amount == total_principal:
        return Decimal(0)

    with localcontext() as context:
        context.prec = 40
        lower = Decimal(0)
        upper = Decimal("0.01")
        while (
            _installment_future_value(
                monthly_payment=monthly_payment,
                monthly_rate=upper,
                months=months,
                contribution_timing=contribution_timing,
            )
            < maturity_amount
        ):
            upper *= Decimal(2)

        for _ in range(160):
            midpoint = (lower + upper) / Decimal(2)
            projected = _installment_future_value(
                monthly_payment=monthly_payment,
                monthly_rate=midpoint,
                months=months,
                contribution_timing=contribution_timing,
            )
            if projected < maturity_amount:
                lower = midpoint
            else:
                upper = midpoint

        monthly_return = (lower + upper) / Decimal(2)
        return (Decimal(1) + monthly_return) ** 12 - Decimal(1)
