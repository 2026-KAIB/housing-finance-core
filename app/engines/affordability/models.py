"""Contracts for combining property, cash, cost, and loan calculations."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.engines.loan.combination_models import (
    CombinationStatus,
    LoanCombinationPlan,
    LoanCombinationResult,
)
from app.engines.purchase_costs.models import PurchaseCostResult


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


class AffordabilityVerdict(StrEnum):
    AFFORDABLE = "AFFORDABLE"
    TIGHT = "TIGHT"
    SHORTFALL = "SHORTFALL"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class PropertyAffordabilityInput:
    """Already-calculated facts needed for one deterministic verdict.

    The orchestration service supplies the outputs of the existing engines.
    This engine does not query a database or recalculate tax, cashflow, or loans.
    """

    as_of: date
    listing_id: str
    purchase_price: Decimal
    purchase_costs: PurchaseCostResult
    usable_liquid_assets: Decimal
    emergency_fund_target: Decimal
    protected_liquid_assets: Decimal
    cashflow_buffer_target: Decimal
    loan_combination: LoanCombinationResult | None = None
    loan_missing_inputs: tuple[str, ...] = ()
    loan_reasons: tuple[str, ...] = ()
    loan_assumptions: tuple[str, ...] = ()
    cashflow_assumptions: tuple[str, ...] = ()
    cashflow_policy_sources: tuple[str, ...] = ()
    loan_policy_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.listing_id.strip():
            raise ValueError("listing_id must not be blank")
        for name, value in (
            ("purchase_price", self.purchase_price),
            ("usable_liquid_assets", self.usable_liquid_assets),
            ("emergency_fund_target", self.emergency_fund_target),
            ("protected_liquid_assets", self.protected_liquid_assets),
            ("cashflow_buffer_target", self.cashflow_buffer_target),
        ):
            _require_non_negative(value, name)
        if self.purchase_price <= 0:
            raise ValueError("purchase_price must be greater than zero")
        if self.protected_liquid_assets > self.emergency_fund_target:
            raise ValueError("protected_liquid_assets must not exceed emergency_fund_target")
        if self.purchase_costs.as_of != self.as_of:
            raise ValueError("purchase cost and affordability dates must match")
        if self.purchase_costs.purchase_price != self.purchase_price:
            raise ValueError("purchase cost price must match the property price")


@dataclass(frozen=True)
class PropertyAffordabilityResult:
    as_of: date
    policy_version: str
    listing_id: str
    verdict: AffordabilityVerdict
    purchase_price: Decimal
    purchase_costs: PurchaseCostResult
    minimum_total_purchase_cost: Decimal
    total_purchase_cost: Decimal | None
    evaluated_purchase_cost: Decimal
    usable_liquid_assets_before_purchase: Decimal
    own_funds_used: Decimal
    remaining_usable_liquid_assets: Decimal
    emergency_fund_target: Decimal
    protected_liquid_assets: Decimal
    minimum_required_loan_amount: Decimal
    required_loan_amount: Decimal | None
    loan_combination_status: CombinationStatus | None
    selected_loan_plan: LoanCombinationPlan | None
    loan_funding_amount: Decimal | None
    minimum_funding_gap: Decimal | None
    funding_gap: Decimal | None
    monthly_loan_payment: Decimal | None
    post_purchase_monthly_surplus: Decimal | None
    stress_monthly_surplus: Decimal | None
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    policy_sources: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        if not self.listing_id.strip():
            raise ValueError("listing_id must not be blank")
        for name, value in (
            ("purchase_price", self.purchase_price),
            ("minimum_total_purchase_cost", self.minimum_total_purchase_cost),
            ("evaluated_purchase_cost", self.evaluated_purchase_cost),
            (
                "usable_liquid_assets_before_purchase",
                self.usable_liquid_assets_before_purchase,
            ),
            ("own_funds_used", self.own_funds_used),
            (
                "remaining_usable_liquid_assets",
                self.remaining_usable_liquid_assets,
            ),
            ("emergency_fund_target", self.emergency_fund_target),
            ("protected_liquid_assets", self.protected_liquid_assets),
            ("minimum_required_loan_amount", self.minimum_required_loan_amount),
        ):
            _require_non_negative(value, name)
        for name, value in (
            ("total_purchase_cost", self.total_purchase_cost),
            ("required_loan_amount", self.required_loan_amount),
            ("loan_funding_amount", self.loan_funding_amount),
            ("minimum_funding_gap", self.minimum_funding_gap),
            ("funding_gap", self.funding_gap),
            ("monthly_loan_payment", self.monthly_loan_payment),
        ):
            if value is not None:
                _require_non_negative(value, name)
        if (
            self.own_funds_used + self.remaining_usable_liquid_assets
            != self.usable_liquid_assets_before_purchase
        ):
            raise ValueError("used and remaining own funds must equal usable liquid assets")
        if self.total_purchase_cost is None:
            if self.required_loan_amount is not None or self.funding_gap is not None:
                raise ValueError("unknown total purchase cost cannot have final loan or gap values")
        elif self.required_loan_amount != max(
            self.total_purchase_cost
            - min(
                self.usable_liquid_assets_before_purchase,
                self.total_purchase_cost,
            ),
            Decimal(0),
        ):
            raise ValueError("required_loan_amount is inconsistent with total cost")
        if self.selected_loan_plan is None:
            if any(
                value is not None
                for value in (
                    self.monthly_loan_payment,
                    self.post_purchase_monthly_surplus,
                    self.stress_monthly_surplus,
                )
            ):
                raise ValueError("loan plan metrics require a selected loan plan")
        if self.purchase_price != self.purchase_costs.purchase_price:
            raise ValueError("result price must match purchase-cost price")
        if self.minimum_total_purchase_cost != (self.purchase_costs.minimum_total_purchase_cost):
            raise ValueError("minimum total must match the purchase-cost result")
        if self.total_purchase_cost != self.purchase_costs.total_purchase_cost:
            raise ValueError("total purchase cost must match the purchase-cost result")
        expected_evaluated = self.total_purchase_cost or self.minimum_total_purchase_cost
        if self.evaluated_purchase_cost != expected_evaluated:
            raise ValueError("evaluated purchase cost must use total or minimum cost")
        expected_own_funds = min(
            self.usable_liquid_assets_before_purchase,
            self.evaluated_purchase_cost,
        )
        if self.own_funds_used != expected_own_funds:
            raise ValueError("own_funds_used is inconsistent with usable assets")
        expected_minimum_loan = max(
            self.minimum_total_purchase_cost - self.usable_liquid_assets_before_purchase,
            Decimal(0),
        )
        if self.minimum_required_loan_amount != expected_minimum_loan:
            raise ValueError("minimum required loan amount is inconsistent")
        if self.loan_funding_amount is None:
            if self.minimum_funding_gap is not None:
                raise ValueError("unknown loan funding cannot have a minimum gap")
        elif self.minimum_funding_gap != max(
            self.minimum_required_loan_amount - self.loan_funding_amount,
            Decimal(0),
        ):
            raise ValueError("minimum funding gap is inconsistent")
        if (
            self.required_loan_amount is not None
            and self.loan_funding_amount is not None
            and self.funding_gap
            != max(
                self.required_loan_amount - self.loan_funding_amount,
                Decimal(0),
            )
        ):
            raise ValueError("funding gap is inconsistent")
        if self.selected_loan_plan is not None:
            if self.loan_funding_amount != self.selected_loan_plan.total_amount:
                raise ValueError("selected plan amount must match loan funding")
        elif self.loan_funding_amount not in (None, Decimal(0)):
            raise ValueError("positive loan funding requires a selected plan")
        if (
            self.verdict
            in {
                AffordabilityVerdict.AFFORDABLE,
                AffordabilityVerdict.TIGHT,
            }
            and self.total_purchase_cost is None
        ):
            raise ValueError("positive affordability verdict requires a known total")
