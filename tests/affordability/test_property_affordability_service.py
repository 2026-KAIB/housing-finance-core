from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.loan_engine_adapter import BorrowerFinancialState
from app.engines.affordability import AffordabilityVerdict
from app.engines.cashflow import CashflowInput, calculate_cashflow
from app.engines.loan.combination_models import (
    CombinationStatus,
    CreditStressRegime,
    LoanCombinationPlan,
    LoanCombinationResult,
)
from app.engines.purchase_costs import PurchaseCostInput
from app.regulations.mortgage_limits import HousingStatus
from app.regulations.regulated_regions import ResolvedRegion
from app.rule_engine.product_packs.handoff import (
    ProductCandidate as LoanProductCandidate,
)
from app.schemas.property import (
    ListingStatus,
    PropertyCandidate,
    PropertyRegion,
    PropertyType,
    TransactionType,
)
from app.services.loan_simulation import LoanSimulationResult
from app.services.property_affordability import (
    PropertyAffordabilityCase,
    PropertyLoanProfile,
    assess_property_affordability,
    assess_property_candidates,
    build_property_affordability_case,
)
from app.services.simulation_result import to_json_value

_AS_OF = date(2026, 7, 30)


def _candidate(
    listing_id: str = "MOCK-GWANAK-001",
    *,
    price: Decimal = Decimal("100000000"),
    sigungu_code: str = "11620",
) -> PropertyCandidate:
    return PropertyCandidate(
        listing_id=listing_id,
        source_listing_id=f"SOURCE-{listing_id}",
        status=ListingStatus.ACTIVE,
        transaction_type=TransactionType.SALE,
        property_type=PropertyType.VILLA,
        property_name="가상 매물",
        region=PropertyRegion(
            sido_code=sigungu_code[:2],
            sigungu_code=sigungu_code,
            address_summary="가상 주소",
        ),
        price_krw=price,
        exclusive_area_m2=Decimal("59"),
        listed_at=datetime(2026, 7, 1, tzinfo=UTC),
        updated_at=datetime(2026, 7, 29, tzinfo=UTC),
    )


def _case(
    listing_id: str = "MOCK-GWANAK-001",
    *,
    price: Decimal = Decimal("100000000"),
    registration: Decimal | None = Decimal("350000"),
    sigungu_code: str = "11620",
) -> PropertyAffordabilityCase:
    candidate = _candidate(
        listing_id,
        price=price,
        sigungu_code=sigungu_code,
    )
    return PropertyAffordabilityCase(
        candidate=candidate,
        purchase_cost_input=PurchaseCostInput(
            as_of=_AS_OF,
            purchase_price=price,
            buyer_is_corporation=False,
            household_home_count_after_purchase=1,
            is_registered_housing=True,
            is_luxury_home=False,
            exclusive_area_m2=Decimal("59"),
            registration_and_legal_costs=registration,
        ),
    )


def _cashflow(liquid_assets: Decimal = Decimal("40000000")):
    return calculate_cashflow(
        CashflowInput(
            as_of=_AS_OF,
            current_monthly_income=Decimal("5000000"),
            current_monthly_essential_expense=Decimal("2000000"),
            monthly_debt_payment=Decimal(0),
            liquid_assets=liquid_assets,
            current_emergency_reserve=Decimal("6000000"),
            income_volatility_risk_override=Decimal(0),
            expense_volatility_risk_override=Decimal(0),
            debt_burden_risk_override=Decimal(0),
            family_medical_risk=Decimal(0),
        )
    )


def _loan_profile() -> PropertyLoanProfile:
    return PropertyLoanProfile(
        borrower=BorrowerFinancialState(
            annual_income=Decimal("60000000"),
            existing_annual_debt_service=Decimal(0),
            post_purchase_monthly_income=Decimal("5000000"),
            post_purchase_monthly_expense=Decimal("2000000"),
            other_existing_monthly_debt_service=Decimal(0),
            monthly_essential_expense=Decimal("2000000"),
            safe_dsr=Decimal("0.40"),
        ),
        housing_status=HousingStatus.FIRST_HOME_BUYER,
        months=360,
        user_facts={
            "age": 30,
            "owned_house_count": 0,
            "is_first_home_buyer": True,
        },
        credit_loan_balance=Decimal(0),
    )


def _real_loan_candidates() -> tuple[LoanProductCandidate, ...]:
    return (
        LoanProductCandidate(
            product_name="KB 주택담보대출",
            base_data={
                "source_type": "manual_pdf",
                "fin_prdt_nm": "KB 주택담보대출",
                "loan_lmt": (
                    "담보조사가격 및 소득금액, 담보물건지 지역 등에 따른 대출가능금액 이내"
                ),
            },
            option_list=(
                {
                    "fin_prdt_nm": "KB 주택담보대출",
                    "mrtg_type_nm": "주택",
                    "rpay_type_nm": "분할상환방식",
                    "lend_rate_type_nm": "고정금리",
                    "lend_rate_min": 4.0,
                    "lend_rate_max": 4.0,
                    "lend_rate_avg": 4.0,
                },
            ),
        ),
    )


def _covering_plan(target: Decimal) -> LoanCombinationPlan:
    return LoanCombinationPlan(
        plan_id="service-plan",
        legs=(),
        total_amount=target,
        funding_shortfall=Decimal(0),
        covers_required_amount=True,
        monthly_payment=Decimal("400000"),
        assessment_monthly_payment=Decimal("500000"),
        expected_dsr=Decimal("0.25"),
        assessment_dsr=Decimal("0.30"),
        post_purchase_monthly_surplus=Decimal("2600000"),
        stress_monthly_surplus=Decimal("2500000"),
        total_interest=Decimal("20000000"),
        total_financial_cost=Decimal("20000000"),
        credit_regime=CreditStressRegime.NOT_APPLICABLE,
    )


def test_service_uses_purchase_cost_and_protected_cash_in_required_loan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_simulate(request, candidates, *, registry=None):
        captured["request"] = request
        captured["candidates"] = candidates
        return LoanSimulationResult(
            policy_as_of=_AS_OF,
            policy_sources=("loan-policy",),
        )

    def fake_combine(request, result, *, supplements=None, policy=None):
        plan = _covering_plan(request.required_amount)
        return LoanCombinationResult(
            status=CombinationStatus.COMPLETE,
            plans=(plan,),
        )

    monkeypatch.setattr(
        "app.services.property_affordability.simulate_loan_options",
        fake_simulate,
    )
    monkeypatch.setattr(
        "app.services.property_affordability.combine_loan_options",
        fake_combine,
    )

    result = assess_property_affordability(
        _case(),
        cashflow_result=_cashflow(),
        loan_profile=_loan_profile(),
        loan_candidates=(object(),),  # type: ignore[arg-type]
    )

    request = captured["request"]
    # 부대비용 포함 총 1.02억 - 비상자금 600만원을 뺀 사용 가능 자금 3400만원.
    assert request.required_amount == Decimal("68000000")  # type: ignore[union-attr]
    assert request.house_price == Decimal("100000000")  # type: ignore[union-attr]
    assert request.user_facts["requested_amount"] == Decimal("68000000")  # type: ignore[union-attr]
    assert result.verdict is AffordabilityVerdict.AFFORDABLE
    assert result.policy_sources[-1] == "loan-policy"


def test_missing_loan_candidates_is_unknown_not_zero_capacity() -> None:
    result = assess_property_affordability(
        _case(),
        cashflow_result=_cashflow(),
        loan_profile=_loan_profile(),
        loan_candidates=(),
    )

    assert result.verdict is AffordabilityVerdict.UNKNOWN
    assert result.loan_funding_amount is None
    assert "loan_product_candidates" in result.missing_inputs


def test_property_loan_profile_date_and_assumptions_reach_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_build_request_for_region(**kwargs):
        captured.update(kwargs)
        return ResolvedRegion(zone=None, note="unresolved test region")

    monkeypatch.setattr(
        "app.services.property_affordability.build_request_for_region",
        fake_build_request_for_region,
    )
    profile = replace(
        _loan_profile(),
        regulation_as_of=date(2026, 7, 1),
        assumptions=("derived borrower fact",),
    )

    result = assess_property_affordability(
        _case(),
        cashflow_result=_cashflow(),
        loan_profile=profile,
        loan_candidates=(object(),),  # type: ignore[arg-type]
    )

    assert captured["as_of"] == date(2026, 7, 1)
    assert "derived borrower fact" in result.assumptions


def test_real_cost_loan_and_combination_engines_work_end_to_end() -> None:
    result = assess_property_affordability(
        _case(),
        cashflow_result=_cashflow(),
        loan_profile=_loan_profile(),
        loan_candidates=_real_loan_candidates(),
    )

    assert result.verdict is AffordabilityVerdict.TIGHT
    assert result.required_loan_amount == Decimal("68000000")
    assert result.loan_funding_amount is not None
    assert result.required_loan_amount - result.loan_funding_amount <= Decimal("100000")
    assert result.selected_loan_plan is not None
    assert result.selected_loan_plan.product_names == ("KB 주택담보대출",)
    assert result.loan_combination_status is CombinationStatus.COMPLETE


def test_cash_purchase_does_not_require_loan_dependencies() -> None:
    result = assess_property_affordability(
        _case(price=Decimal("20000000")),
        cashflow_result=_cashflow(),
    )

    assert result.verdict is AffordabilityVerdict.AFFORDABLE
    assert result.required_loan_amount == 0
    assert "property_loan_profile" not in result.missing_inputs


def test_unknown_region_is_reported_without_falling_back_to_non_regulated() -> None:
    result = assess_property_affordability(
        _case(sigungu_code="99999"),
        cashflow_result=_cashflow(),
        loan_profile=_loan_profile(),
        loan_candidates=(object(),),  # type: ignore[arg-type]
    )

    assert result.verdict is AffordabilityVerdict.UNKNOWN
    assert "regulation_region" in result.missing_inputs
    assert any("비규제지역" in reason for reason in result.reasons)


def test_batch_preserves_search_order_and_json_decimal_precision() -> None:
    results = assess_property_candidates(
        (
            _case("LISTING-A", price=Decimal("20000000")),
            _case("LISTING-B", price=Decimal("25000000")),
        ),
        cashflow_result=_cashflow(),
    )

    assert [result.listing_id for result in results] == [
        "LISTING-A",
        "LISTING-B",
    ]
    payload = to_json_value(results[0])
    assert payload["purchase_price"] == "20000000"
    assert payload["verdict"] == "AFFORDABLE"


def test_case_rejects_a_cost_input_for_another_property_price() -> None:
    with pytest.raises(ValueError, match="must match"):
        PropertyAffordabilityCase(
            candidate=_candidate(price=Decimal("100000000")),
            purchase_cost_input=PurchaseCostInput(
                as_of=_AS_OF,
                purchase_price=Decimal("99000000"),
            ),
        )


def test_case_builder_copies_price_and_area_from_json_candidate() -> None:
    candidate = _candidate(price=Decimal("123000000"))
    case = build_property_affordability_case(
        candidate,
        as_of=_AS_OF,
        buyer_is_corporation=False,
        household_home_count_after_purchase=1,
        is_registered_housing=True,
        is_luxury_home=False,
    )

    assert case.purchase_cost_input.purchase_price == candidate.price_krw
    assert case.purchase_cost_input.exclusive_area_m2 == candidate.exclusive_area_m2


def test_case_rejects_an_inactive_listing() -> None:
    candidate = _candidate().model_copy(update={"status": ListingStatus.INACTIVE})

    with pytest.raises(ValueError, match="active"):
        PropertyAffordabilityCase(
            candidate=candidate,
            purchase_cost_input=_case().purchase_cost_input,
        )


def test_batch_rejects_duplicate_listing_ids() -> None:
    case = _case("DUPLICATE", price=Decimal("20000000"))

    with pytest.raises(ValueError, match="duplicates"):
        assess_property_candidates(
            (case, case),
            cashflow_result=_cashflow(),
        )


def test_service_rejects_mismatched_calculation_dates() -> None:
    older = calculate_cashflow(
        CashflowInput(
            as_of=date(2026, 7, 29),
            current_monthly_income=Decimal("5000000"),
            current_monthly_essential_expense=Decimal("2000000"),
        )
    )

    with pytest.raises(ValueError, match="dates must match"):
        assess_property_affordability(
            _case(price=Decimal("20000000")),
            cashflow_result=older,
        )
