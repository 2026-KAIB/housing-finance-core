from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.data_pipeline.adapters.loan_engine_adapter import BorrowerFinancialState
from app.regulations.mortgage_limits import (
    DTI_RATIOS,
    HousingStatus,
    RegulationZone,
    resolve_dti_limit_amount,
)
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.rule_engine.product_packs.models import (
    ProductCategory,
    ProductRulePack,
)
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule
from app.services.loan_simulation import (
    LoanSimulationRequest,
    simulate_loan_options,
    summarize,
)

_AS_OF = date(2026, 7, 28)

# 금리가 크게 다른 두 옵션. DTI 한도를 옵션별로 환산하는지 보려면 필요하다.
_BASE = {
    "source_type": "manual_pdf",
    "fin_prdt_nm": "KB 주택담보대출",
    "loan_lmt": (
        "담보조사가격 및 소득금액, 담보물건지 지역 등에 따른 대출가능금액 이내 "
        "(통장자동대출 최고 3억원 이내)"
    ),
}
_OPTIONS = (
    {
        "fin_prdt_nm": "KB 주택담보대출",
        "mrtg_type_nm": "아파트",
        "rpay_type_nm": "분할상환방식",
        "lend_rate_type_nm": "변동금리",
        "lend_rate_min": 3.0,
        "lend_rate_max": 3.0,
        "lend_rate_avg": 3.0,
    },
    {
        "fin_prdt_nm": "KB 주택담보대출",
        "mrtg_type_nm": "아파트",
        "rpay_type_nm": "분할상환방식",
        "lend_rate_type_nm": "고정금리",
        "lend_rate_min": 9.0,
        "lend_rate_max": 9.0,
        "lend_rate_avg": 9.0,
    },
)
_PACK = ProductRulePack(
    product_name="KB 주택담보대출",
    category=ProductCategory.MORTGAGE_LOAN,
    version="test-1",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    rules=(
        ComparisonRule(
            code="TEST_MIN_AGE",
            field_name="age",
            operator=ComparisonOperator.GTE,
            expected=19,
            failure_reason="미성년자는 신청할 수 없습니다.",
        ),
    ),
)

_BORROWER = BorrowerFinancialState(
    annual_income=Decimal("60000000"),
    existing_annual_debt_service=Decimal("6000000"),
    post_purchase_monthly_income=Decimal("5000000"),
    post_purchase_monthly_expense=Decimal("2000000"),
    other_existing_monthly_debt_service=Decimal("500000"),
    monthly_essential_expense=Decimal("2000000"),
    safe_dsr=Decimal("0.40"),
)


def _candidates() -> list[ProductCandidate]:
    return [
        ProductCandidate(
            product_name="KB 주택담보대출",
            base_data=_BASE,
            option_list=_OPTIONS,
        )
    ]


def _request(**overrides: object) -> LoanSimulationRequest:
    defaults: dict[str, object] = {
        "borrower": _BORROWER,
        "user_facts": {"age": 34, "is_overdraft_type": False},
        "house_price": Decimal("800000000"),
        "zone": RegulationZone.SPECULATION_OVERHEATED,
        "housing_status": HousingStatus.NO_HOUSE,
        "is_capital_region": True,
        "required_amount": Decimal("300000000"),
        "months": 360,
        "as_of": _AS_OF,
    }
    defaults.update(overrides)
    return LoanSimulationRequest(**defaults)  # type: ignore[arg-type]


def _run(**overrides: object):
    return simulate_loan_options(
        _request(**overrides),
        _candidates(),
        registry=ProductRulePackRegistry((_PACK,)),
    )


class TestRegulationIsActuallyCalled:
    """규제 해석기가 실제 계산 흐름에서 불리는지. 예전에는 테스트에서만 불렸다."""

    def test_ltv_comes_from_the_regulation_table(self) -> None:
        result = _run()
        assert result.ltv is not None
        # 8억 × 40%(규제지역 무주택) = 3.2억. 15억 이하 구간 한도 6억보다 낮다.
        assert result.ltv.amount == Decimal("320000000")
        assert result.ltv.binding_reason == "LTV 40%"

    def test_result_records_the_policy_basis(self) -> None:
        result = _run()
        assert result.policy_as_of == _AS_OF
        assert result.policy_sources  # 출처 없이 숫자만 내보내지 않는다
        assert any("규제 기준일" in note for note in result.notes)

    def test_first_home_buyer_gets_the_relaxed_ratio(self) -> None:
        result = _run(housing_status=HousingStatus.FIRST_HOME_BUYER)
        assert result.ltv is not None
        # 8억 × 70% = 5.6억
        assert result.ltv.amount == Decimal("560000000")

    def test_grandfathered_reference_date_changes_the_answer(self) -> None:
        # 경과규정 대상 차주는 as_of에 종전 기준일을 넘긴다.
        before = _run(
            zone=RegulationZone.ADJUSTMENT_TARGET,
            as_of=date(2026, 6, 30),
            allow_unverified_regulation=True,
        )
        after = _run(zone=RegulationZone.ADJUSTMENT_TARGET)
        assert before.ltv is not None and after.ltv is not None
        assert before.ltv.amount is not None and after.ltv.amount is not None
        assert before.ltv.amount > after.ltv.amount


class TestUnresolvedRegulationStopsTheRun:
    def test_missing_ltv_reports_instead_of_guessing(self) -> None:
        # 비규제지역 생애최초 80%는 미검증이라 기본적으로 반환되지 않는다.
        result = _run(
            zone=RegulationZone.NON_REGULATED,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            is_capital_region=False,
        )
        assert not result.is_resolved
        assert "ltv_ratio" in result.missing_inputs
        # 규제를 모르면 상품 계산으로 넘어가지 않는다 — 근거 없는 숫자를 만들지 않는다.
        assert result.executable == ()
        assert result.not_executable == ()
        assert "규제 한도를 확정하지" in summarize(result)[0]

    def test_unknown_dti_region_is_reported(self) -> None:
        result = _run(dti_region="존재하지 않는 지역")
        assert not result.is_resolved
        assert "dti_ratio" in result.missing_inputs

    def test_allowing_unverified_values_is_recorded_in_the_notes(self) -> None:
        result = _run(
            zone=RegulationZone.NON_REGULATED,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            is_capital_region=False,
            allow_unverified_regulation=True,
        )
        assert result.is_resolved
        assert any("미검증" in note for note in result.notes)


class TestDtiIsResolvedPerOption:
    """옵션마다 금리·만기가 다르면 DTI 한도도 달라야 한다.

    하나의 DTI 금액을 모든 옵션에 공유하면 금리가 낮은 옵션의 한도가 그대로
    높은 옵션에 쓰여 대출가능액이 과대평가된다.
    """

    def test_a_higher_rate_option_never_allows_more(self) -> None:
        result = _run()
        by_rate = {
            computation.option.rate("avg"): computation.amount
            for computation in result.executable
            if computation.option is not None
        }
        assert len(by_rate) == 2, by_rate

        cheap = by_rate[Decimal("0.03")]
        expensive = by_rate[Decimal("0.09")]
        assert expensive < cheap, "금리 9% 옵션이 3% 옵션보다 많이 빌릴 수 있을 수 없다"

    def test_every_option_produces_its_own_result(self) -> None:
        result = _run()
        assert len(result.executable) + len(result.not_executable) == len(_OPTIONS)

    def test_the_expensive_option_is_bound_by_its_own_dti_limit(self) -> None:
        """공유 DTI를 쓰면 답이 달라진다는 것을 고정한다.

        주의: 기본 `safe_dsr`(40%)가 DTI 비율(50%)보다 낮으면 DSR이 항상 먼저
        걸려 DTI가 구속하지 않는다. 그 상태로는 옵션별 환산을 지워도 결과가
        같아서 이 수정을 지키지 못한다. 그래서 DTI가 실제로 구속하도록
        `safe_dsr`을 DTI 비율 위로 올려 두고 검사한다.
        """
        borrower = replace(_BORROWER, safe_dsr=Decimal("0.70"))
        result = _run(borrower=borrower)

        def dti_for(rate: str) -> Decimal:
            amount = resolve_dti_limit_amount(
                annual_income=borrower.annual_income,
                dti_ratio=DTI_RATIOS["SEOUL"].ratio,
                other_annual_interest=borrower.existing_annual_debt_service,
                annual_rate=Decimal(rate),
                months=360,
            ).amount
            assert amount is not None
            return amount

        cheap_dti, expensive_dti = dti_for("0.03"), dti_for("0.09")
        # 같은 차주라도 금리가 높으면 같은 연 상환액으로 갚을 수 있는 원금이 적다.
        assert expensive_dti < cheap_dti

        by_rate = {
            computation.option.rate("avg"): computation.amount
            for computation in result.executable
            if computation.option is not None
        }
        # 고금리 옵션은 자기 DTI 한도에 묶인다. 저금리 옵션의 한도를 공유했다면
        # 이 상한을 넘어섰을 것이다.
        assert by_rate[Decimal("0.09")] <= expensive_dti


class TestResultPartitioning:
    """빠진 이유가 서로 다르므로 한 덩어리로 뭉치지 않는다."""

    def test_ineligible_borrower_lands_in_rejected(self) -> None:
        result = _run(user_facts={"age": 17, "is_overdraft_type": False})
        assert result.rejected
        assert result.executable == ()
        assert any("미성년자" in reason for a in result.rejected for reason in a.reasons)

    def test_eligible_borrower_lands_in_executable(self) -> None:
        result = _run()
        assert result.executable
        assert result.rejected == ()
        assert result.unresolved == ()

    def test_best_picks_the_largest_executable_amount(self) -> None:
        result = _run()
        best = result.best
        assert best is not None
        assert best.amount == max(c.amount for c in result.executable)

    def test_best_is_none_when_nothing_is_executable(self) -> None:
        result = _run(user_facts={"age": 17, "is_overdraft_type": False})
        assert result.best is None


class TestConservativeAssumptionsSurvive:
    def test_assumptions_reach_the_final_result(self) -> None:
        # is_overdraft_type를 모르면 상품 한도를 보수적으로 낮춰 잡고 가정을 남긴다.
        result = _run(user_facts={"age": 34})
        assert result.executable
        assert all(c.assumptions for c in result.executable)
        assert any("is_overdraft_type" in c.assumptions[0] for c in result.executable)

    def test_conservative_run_never_exceeds_the_fully_specified_one(self) -> None:
        known = _run(user_facts={"age": 34, "is_overdraft_type": False})
        unknown = _run(user_facts={"age": 34})
        assert known.best is not None and unknown.best is not None
        assert unknown.best.amount <= known.best.amount
