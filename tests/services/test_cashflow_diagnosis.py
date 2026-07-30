from datetime import date
from decimal import Decimal

from app.engines.cashflow import CashflowEngineStatus
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    SimulationInput,
    UserProfile,
)
from app.services.cashflow_diagnosis import diagnose_cashflow


def _payload(*, emergency_reserve: Decimal | None = Decimal("2000000")) -> SimulationInput:
    return SimulationInput(
        profile=UserProfile(
            age=30,
            household_size=1,
            annual_income=Decimal("48000000"),
            employment_type="salaried",
        ),
        housing_goal=HousingGoal(
            target_amount=Decimal("300000000"),
            target_date=date(2030, 12, 31),
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("3500000"),
            monthly_expense=Decimal("1800000"),
            liquid_assets=Decimal("10000000"),
            monthly_debt_payment=Decimal("200000"),
            emergency_reserve=emergency_reserve,
        ),
    )


def test_public_snapshot_is_adapted_without_fabricating_history() -> None:
    result = diagnose_cashflow(_payload(), as_of=date(2026, 7, 30))

    assert result.status is CashflowEngineStatus.PARTIAL
    assert result.diagnosis.safe_monthly_income == Decimal("3500000")
    assert result.diagnosis.safe_monthly_essential_expense == Decimal("1800000")
    assert result.diagnosis.monthly_debt_payment == Decimal("200000")
    assert "monthly_income_history" in result.missing_inputs
    assert "family_medical_risk" in result.missing_inputs
    assert any("monthly_expense 전액" in assumption for assumption in result.assumptions)


def test_missing_reserve_remains_unknown_through_the_adapter() -> None:
    result = diagnose_cashflow(
        _payload(emergency_reserve=None),
        as_of=date(2026, 7, 30),
    )

    assert result.emergency_fund.current_amount is None
    assert result.emergency_fund.shortfall_amount is None
    assert result.allocation.monthly_housing_savings_available is None
