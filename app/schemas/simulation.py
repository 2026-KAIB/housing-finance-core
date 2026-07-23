from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    age: int = Field(ge=19, le=120)
    household_size: int = Field(default=1, ge=1)
    annual_income: Decimal = Field(ge=0)
    is_first_home_buyer: bool = False
    is_married: bool = False
    region_code: str | None = None


class HousingGoal(BaseModel):
    target_price: Decimal = Field(gt=0)
    target_date: date
    region_code: str | None = None


class FinancialSnapshot(BaseModel):
    monthly_income: Decimal = Field(ge=0)
    monthly_expense: Decimal = Field(ge=0)
    liquid_assets: Decimal = Field(ge=0)
    housing_assets: Decimal = Field(default=Decimal("0"), ge=0)
    total_debt: Decimal = Field(default=Decimal("0"), ge=0)
    monthly_debt_payment: Decimal = Field(default=Decimal("0"), ge=0)


class SimulationInput(BaseModel):
    profile: UserProfile
    housing_goal: HousingGoal
    financial_snapshot: FinancialSnapshot


class EngineSummary(BaseModel):
    status: str
    score: Decimal | None = None
    reasons: list[str] = Field(default_factory=list)


class SimulationResult(BaseModel):
    simulation_id: UUID
    calculated_at: date
    cashflow: EngineSummary
    savings: EngineSummary
    loan: EngineSummary
    recommendation: EngineSummary

