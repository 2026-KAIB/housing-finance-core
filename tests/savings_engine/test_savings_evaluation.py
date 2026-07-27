from datetime import date
from decimal import Decimal

from app.engines.savings.evaluation import add_months, evaluate_savings_option
from app.engines.savings.models import (
    InterestType,
    SavingsCalculationResult,
    SavingsEvaluationInput,
    SavingsEvaluationStatus,
    SavingsProductKind,
)

CALCULATION = SavingsCalculationResult(
    product_name="테스트 정기예금",
    product_kind=SavingsProductKind.TERM_DEPOSIT,
    term_months=12,
    interest_type=InterestType.SIMPLE,
    reserve_type_name=None,
    annual_base_rate=Decimal("0.03"),
    annual_max_rate=Decimal("0.05"),
    expected_annual_rate=Decimal("0.05"),
    bonus_achievement_probability=Decimal("0.8"),
    total_principal=Decimal("10000000"),
    gross_interest=Decimal("500000"),
    tax_amount=Decimal("77000"),
    net_interest=Decimal("423000"),
    maturity_amount=Decimal("10423000"),
    annualized_net_return_rate=Decimal("0.04"),
    net_return_rate=Decimal("0.0423"),
)


def _payload(**changes: object) -> SavingsEvaluationInput:
    values: dict[str, object] = {
        "calculation": CALCULATION,
        "as_of": date(2026, 7, 27),
        "fund_needed_date": date(2027, 7, 27),
        "maturity_tolerance_days": 180,
        "market_min_rate": Decimal("0.02"),
        "market_max_rate": Decimal("0.04"),
        "liquidity_score": Decimal("0.5"),
        "is_principal_protected": True,
        "accepts_principal_risk": False,
        "is_deposit_protected": True,
        "existing_institution_deposit": Decimal("0"),
        "deposit_protection_limit": Decimal("50000000"),
    }
    values.update(changes)
    return SavingsEvaluationInput(**values)  # type: ignore[arg-type]


def test_score_uses_documented_weights_after_hard_filters() -> None:
    result = evaluate_savings_option(_payload())

    assert result.status is SavingsEvaluationStatus.ELIGIBLE
    assert result.score == Decimal("88.000")
    assert result.components is not None
    assert result.components.maturity_fit_score == Decimal(1)


def test_maturity_after_fund_needed_date_is_filtered_before_scoring() -> None:
    result = evaluate_savings_option(
        _payload(fund_needed_date=date(2027, 6, 30))
    )

    assert result.status is SavingsEvaluationStatus.INELIGIBLE
    assert result.score is None
    assert "자금 필요시점" in result.reasons[0]


def test_deposit_protection_limit_is_a_hard_filter() -> None:
    result = evaluate_savings_option(
        _payload(
            existing_institution_deposit=Decimal("45000000"),
            deposit_protection_limit=Decimal("50000000"),
        )
    )

    assert result.status is SavingsEvaluationStatus.INELIGIBLE
    assert any("예금자보호 한도" in reason for reason in result.reasons)


def test_add_months_clamps_month_end() -> None:
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
