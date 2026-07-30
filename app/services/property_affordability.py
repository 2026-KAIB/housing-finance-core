"""Orchestrate existing engines for one or more searched property listings."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.data_pipeline.adapters.loan_engine_adapter import BorrowerFinancialState
from app.engines.affordability import (
    DEFAULT_AFFORDABILITY_POLICY,
    AffordabilityPolicy,
    PropertyAffordabilityInput,
    PropertyAffordabilityResult,
    evaluate_property_affordability,
)
from app.engines.cashflow.models import CashflowResult
from app.engines.loan.combination_models import (
    DEFAULT_COMBINATION_POLICY,
    LoanCombinationPolicy,
)
from app.engines.purchase_costs import (
    DEFAULT_PURCHASE_COST_POLICY,
    PurchaseCostEngineStatus,
    PurchaseCostInput,
    PurchaseCostPolicy,
    estimate_purchase_costs,
)
from app.regulations.mortgage_limits import HousingStatus
from app.regulations.regulated_regions import ResolvedRegion
from app.rule_engine.product_packs.handoff import ProductCandidate as LoanProductCandidate
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.schemas.property import ListingStatus, PropertyCandidate
from app.services.loan_combination import combine_loan_options
from app.services.loan_simulation import (
    LoanSimulationRequest,
    build_request_for_region,
    simulate_loan_options,
)
from app.services.recommendation import LoanRecommendationSupplement


@dataclass(frozen=True)
class PropertyAffordabilityCase:
    """One listing plus legal facts needed by the purchase-cost engine."""

    candidate: PropertyCandidate
    purchase_cost_input: PurchaseCostInput

    def __post_init__(self) -> None:
        if self.purchase_cost_input.purchase_price != self.candidate.price_krw:
            raise ValueError("purchase cost price must match candidate price")
        if (
            self.candidate.exclusive_area_m2 is not None
            and self.purchase_cost_input.exclusive_area_m2 is not None
            and self.purchase_cost_input.exclusive_area_m2 != self.candidate.exclusive_area_m2
        ):
            raise ValueError("purchase cost area must match candidate area")
        if self.candidate.status is not ListingStatus.ACTIVE:
            raise ValueError("only active property candidates can be evaluated")


@dataclass(frozen=True)
class PropertyLoanProfile:
    """Borrower facts shared while the property-specific request is rebuilt."""

    borrower: BorrowerFinancialState
    housing_status: HousingStatus
    months: int
    user_facts: Mapping[str, object] = field(default_factory=dict)
    rate_selection: str = "avg"
    for_house_purchase: bool = True
    allow_unverified_regulation: bool = False
    credit_loan_balance: Decimal | None = None

    def __post_init__(self) -> None:
        if self.months <= 0:
            raise ValueError("months must be greater than zero")
        if self.rate_selection not in {"avg", "min", "max"}:
            raise ValueError("rate_selection must be avg, min, or max")
        if not self.for_house_purchase:
            raise ValueError("property affordability supports house-purchase loans only")
        if self.credit_loan_balance is not None and self.credit_loan_balance < 0:
            raise ValueError("credit_loan_balance must not be negative")


def build_property_affordability_case(
    candidate: PropertyCandidate,
    *,
    as_of: date,
    buyer_is_corporation: bool | None = None,
    household_home_count_after_purchase: int | None = None,
    is_registered_housing: bool | None = None,
    is_luxury_home: bool | None = None,
    is_national_housing_scale_override: bool | None = None,
    registration_and_legal_costs: Decimal | None = None,
    brokerage_vat_rate_override: Decimal | None = None,
) -> PropertyAffordabilityCase:
    """Build a cost case without copying the listing price or area by hand."""

    return PropertyAffordabilityCase(
        candidate=candidate,
        purchase_cost_input=PurchaseCostInput(
            as_of=as_of,
            purchase_price=candidate.price_krw,
            buyer_is_corporation=buyer_is_corporation,
            household_home_count_after_purchase=(household_home_count_after_purchase),
            is_registered_housing=is_registered_housing,
            is_luxury_home=is_luxury_home,
            exclusive_area_m2=candidate.exclusive_area_m2,
            is_national_housing_scale_override=(is_national_housing_scale_override),
            registration_and_legal_costs=registration_and_legal_costs,
            brokerage_vat_rate_override=brokerage_vat_rate_override,
        ),
    )


def _loan_request_for_property(
    case: PropertyAffordabilityCase,
    profile: PropertyLoanProfile,
    *,
    required_amount: Decimal,
) -> LoanSimulationRequest | ResolvedRegion:
    facts = dict(profile.user_facts)
    status = profile.housing_status
    owns_house = status.value.startswith("ONE_HOUSE") or status.value == "MULTI_HOUSE"
    facts.update(
        {
            "annual_income": profile.borrower.annual_income,
            "is_first_home_buyer": status is HousingStatus.FIRST_HOME_BUYER,
            "owns_house": owns_house,
            "requested_amount": required_amount,
            # 기존 simulation_orchestrator와 같은 Rule Pack 사실 표현을 쓴다.
            "loan_term_years": profile.months // 12,
        }
    )
    if status in {HousingStatus.NO_HOUSE, HousingStatus.FIRST_HOME_BUYER}:
        facts["owned_house_count"] = 0
    elif status.value.startswith("ONE_HOUSE"):
        facts["owned_house_count"] = 1
    # MULTI_HOUSE는 2채 이상이라는 뜻일 뿐 정확한 수는 아니다. 호출자가
    # 명시한 값은 유지하되, 없으면 2로 추측해 채우지 않는다.
    return build_request_for_region(
        region_code=case.candidate.region.sigungu_code,
        as_of=case.purchase_cost_input.as_of,
        borrower=profile.borrower,
        user_facts=facts,
        house_price=case.candidate.price_krw,
        housing_status=profile.housing_status,
        required_amount=required_amount,
        months=profile.months,
        rate_selection=profile.rate_selection,
        for_house_purchase=profile.for_house_purchase,
        allow_unverified_regulation=profile.allow_unverified_regulation,
        credit_loan_balance=profile.credit_loan_balance,
    )


def assess_property_affordability(
    case: PropertyAffordabilityCase,
    *,
    cashflow_result: CashflowResult,
    loan_profile: PropertyLoanProfile | None = None,
    loan_candidates: Sequence[LoanProductCandidate] = (),
    registry: ProductRulePackRegistry | None = None,
    loan_supplements: Mapping[str, LoanRecommendationSupplement] | None = None,
    purchase_cost_policy: PurchaseCostPolicy = DEFAULT_PURCHASE_COST_POLICY,
    loan_combination_policy: LoanCombinationPolicy = DEFAULT_COMBINATION_POLICY,
    affordability_policy: AffordabilityPolicy = DEFAULT_AFFORDABILITY_POLICY,
) -> PropertyAffordabilityResult:
    """Calculate costs and a property-specific loan combination, then decide."""

    if cashflow_result.as_of != case.purchase_cost_input.as_of:
        raise ValueError("cashflow, purchase cost, and affordability dates must match")

    purchase_costs = estimate_purchase_costs(
        case.purchase_cost_input,
        policy=purchase_cost_policy,
    )
    evaluated_cost = (
        purchase_costs.total_purchase_cost or purchase_costs.minimum_total_purchase_cost
    )
    usable_assets = cashflow_result.emergency_fund.usable_liquid_assets_after_target
    required_amount = max(evaluated_cost - usable_assets, Decimal(0))

    combination = None
    loan_missing: tuple[str, ...] = ()
    loan_reasons: tuple[str, ...] = ()
    loan_sources: tuple[str, ...] = ()

    can_run_loan = purchase_costs.status not in {
        PurchaseCostEngineStatus.UNSUPPORTED,
        PurchaseCostEngineStatus.POLICY_OUT_OF_RANGE,
    }
    if required_amount > 0 and can_run_loan:
        if loan_profile is None:
            loan_missing = ("property_loan_profile",)
            loan_reasons = ("매물별 대출 계산에 필요한 차주·만기·주택보유상태가 없습니다.",)
        elif not loan_candidates:
            loan_missing = ("loan_product_candidates",)
            loan_reasons = (
                "대출 상품 후보가 전달되지 않아 매물별 대출 조합을 계산하지 않았습니다.",
            )
        else:
            built = _loan_request_for_property(
                case,
                loan_profile,
                required_amount=required_amount,
            )
            if isinstance(built, ResolvedRegion):
                loan_missing = ("regulation_region",)
                loan_reasons = (
                    built.note or "매물 지역을 규제지역 구분으로 확정하지 못했습니다.",
                    "임의로 비규제지역으로 보면 LTV가 과대평가되므로 계산하지 않았습니다.",
                )
            else:
                simulation = simulate_loan_options(
                    built,
                    loan_candidates,
                    registry=registry,
                )
                loan_sources = simulation.policy_sources
                combination = combine_loan_options(
                    built,
                    simulation,
                    supplements=loan_supplements,
                    policy=loan_combination_policy,
                )

    return evaluate_property_affordability(
        PropertyAffordabilityInput(
            as_of=case.purchase_cost_input.as_of,
            listing_id=case.candidate.listing_id,
            purchase_price=case.candidate.price_krw,
            purchase_costs=purchase_costs,
            usable_liquid_assets=usable_assets,
            emergency_fund_target=cashflow_result.emergency_fund.target_amount,
            protected_liquid_assets=(cashflow_result.emergency_fund.protected_liquid_assets),
            cashflow_buffer_target=(cashflow_result.diagnosis.cashflow_buffer_target),
            loan_combination=combination,
            loan_missing_inputs=loan_missing,
            loan_reasons=loan_reasons,
            cashflow_assumptions=cashflow_result.assumptions,
            cashflow_policy_sources=cashflow_result.policy_sources,
            loan_policy_sources=loan_sources,
        ),
        policy=affordability_policy,
    )


def assess_property_candidates(
    cases: Sequence[PropertyAffordabilityCase],
    *,
    cashflow_result: CashflowResult,
    loan_profile: PropertyLoanProfile | None = None,
    loan_candidates: Sequence[LoanProductCandidate] = (),
    registry: ProductRulePackRegistry | None = None,
    loan_supplements: Mapping[str, LoanRecommendationSupplement] | None = None,
    purchase_cost_policy: PurchaseCostPolicy = DEFAULT_PURCHASE_COST_POLICY,
    loan_combination_policy: LoanCombinationPolicy = DEFAULT_COMBINATION_POLICY,
    affordability_policy: AffordabilityPolicy = DEFAULT_AFFORDABILITY_POLICY,
) -> tuple[PropertyAffordabilityResult, ...]:
    """Evaluate every searched listing independently in its original order."""

    listing_ids = [case.candidate.listing_id for case in cases]
    if len(listing_ids) != len(set(listing_ids)):
        raise ValueError("property affordability cases must not contain duplicates")
    return tuple(
        assess_property_affordability(
            case,
            cashflow_result=cashflow_result,
            loan_profile=loan_profile,
            loan_candidates=loan_candidates,
            registry=registry,
            loan_supplements=loan_supplements,
            purchase_cost_policy=purchase_cost_policy,
            loan_combination_policy=loan_combination_policy,
            affordability_policy=affordability_policy,
        )
        for case in cases
    )


__all__ = [
    "PropertyAffordabilityCase",
    "PropertyLoanProfile",
    "assess_property_affordability",
    "assess_property_candidates",
    "build_property_affordability_case",
]
