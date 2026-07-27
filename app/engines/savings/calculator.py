from decimal import Decimal

from app.engines.savings.formulas import (
    annualized_deposit_return,
    annualized_installment_return,
    expected_annual_rate,
    installment_savings_gross_maturity,
    interest_tax,
    term_deposit_gross_maturity,
)
from app.engines.savings.models import (
    SavingsCalculationInput,
    SavingsCalculationResult,
    SavingsProductKind,
)


def calculate_savings(payload: SavingsCalculationInput) -> SavingsCalculationResult:
    """정규화·판정이 끝난 예적금 옵션 하나의 만기 결과를 계산한다."""
    annual_rate = expected_annual_rate(
        annual_base_rate=payload.annual_base_rate,
        annual_max_rate=payload.annual_max_rate,
        bonus_achievement_probability=payload.bonus_achievement_probability,
    )

    if payload.product_kind is SavingsProductKind.TERM_DEPOSIT:
        if payload.deposit_amount is None:
            raise ValueError("정기예금 계산에는 deposit_amount가 필요합니다.")
        if payload.monthly_payment_amount is not None:
            raise ValueError("정기예금 계산에는 monthly_payment_amount를 사용할 수 없습니다.")
        if payload.contribution_timing is not None:
            raise ValueError("정기예금 계산에는 contribution_timing을 사용할 수 없습니다.")
        total_principal = payload.deposit_amount
        gross_maturity = term_deposit_gross_maturity(
            principal=total_principal,
            annual_rate=annual_rate,
            months=payload.term_months,
            interest_type=payload.interest_type,
        )
    elif payload.product_kind is SavingsProductKind.INSTALLMENT_SAVINGS:
        if payload.monthly_payment_amount is None:
            raise ValueError("적금 계산에는 monthly_payment_amount가 필요합니다.")
        if payload.deposit_amount is not None:
            raise ValueError("적금 계산에는 deposit_amount를 사용할 수 없습니다.")
        if payload.contribution_timing is None:
            raise ValueError("적금 계산에는 contribution_timing이 필요합니다.")
        total_principal = payload.monthly_payment_amount * Decimal(payload.term_months)
        gross_maturity = installment_savings_gross_maturity(
            monthly_payment=payload.monthly_payment_amount,
            annual_rate=annual_rate,
            months=payload.term_months,
            interest_type=payload.interest_type,
            contribution_timing=payload.contribution_timing,
        )
    else:
        raise ValueError(f"지원하지 않는 예적금 상품 구분입니다: {payload.product_kind!r}")

    gross_interest = gross_maturity - total_principal
    tax_amount = interest_tax(gross_interest=gross_interest, tax_rate=payload.tax_rate)
    net_interest = gross_interest - tax_amount
    maturity_amount = total_principal + net_interest
    net_return_rate = (
        net_interest / total_principal if total_principal > 0 else Decimal("0")
    )
    if payload.product_kind is SavingsProductKind.TERM_DEPOSIT:
        annualized_net_return_rate = annualized_deposit_return(
            principal=total_principal,
            maturity_amount=maturity_amount,
            months=payload.term_months,
        )
    else:
        assert payload.monthly_payment_amount is not None
        assert payload.contribution_timing is not None
        annualized_net_return_rate = annualized_installment_return(
            monthly_payment=payload.monthly_payment_amount,
            maturity_amount=maturity_amount,
            months=payload.term_months,
            contribution_timing=payload.contribution_timing,
        )

    return SavingsCalculationResult(
        product_name=payload.product_name,
        product_kind=payload.product_kind,
        term_months=payload.term_months,
        interest_type=payload.interest_type,
        reserve_type_name=payload.reserve_type_name,
        annual_base_rate=payload.annual_base_rate,
        annual_max_rate=payload.annual_max_rate,
        expected_annual_rate=annual_rate,
        bonus_achievement_probability=payload.bonus_achievement_probability,
        total_principal=total_principal,
        gross_interest=gross_interest,
        tax_amount=tax_amount,
        net_interest=net_interest,
        maturity_amount=maturity_amount,
        annualized_net_return_rate=annualized_net_return_rate,
        net_return_rate=net_return_rate,
    )
