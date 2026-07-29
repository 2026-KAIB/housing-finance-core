from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.data_pipeline.adapters.loan_engine_adapter import (
    BorrowerFinancialState,
    PolicyLimits,
    adapt_handoff_for_loan_max,
)
from app.data_pipeline.curated.loan_limits import resolve_product_limit
from app.engines.loan.formulas import loan_max
from app.regulations.mortgage_limits import (
    DTI_RATIO_HISTORY,
    DtiRegion,
    HousingStatus,
    RegulationZone,
    resolve_dti_limit_amount,
    resolve_dti_ratio,
)
from app.regulations.regulated_regions import ResolvedRegion
from app.rule_engine.product_packs.handoff import ProductCandidate, route_product_candidates
from app.rule_engine.product_packs.models import (
    ProductCategory,
    ProductRulePack,
)
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule
from app.services.loan_simulation import (
    LoanSimulationRequest,
    _align_region_facts,
    build_request_for_region,
    resolve_dti_region,
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

    def test_a_date_before_the_dti_rule_took_effect_is_reported(self) -> None:
        # DTI도 LTV처럼 시행일을 본다. 예전에는 dict 조회 한 번이라
        # 2018년 이전 기준일에도 50%가 그대로 나왔다.
        result = _run(as_of=date(2015, 1, 1), allow_unverified_regulation=True)
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
                dti_ratio=DTI_RATIO_HISTORY[DtiRegion.SEOUL][0].ratio,
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


class TestStressDsrIsApplied:
    """스트레스 DSR — 이 저장소에서 유일하게 **과대평가** 방향인 결측이다.

    다른 결측은 빠뜨리면 한도가 낮게 나와 안전하지만, 스트레스 금리를 빠뜨리면
    실제로 못 빌리는 금액을 빌릴 수 있다고 말하게 된다. 그래서 확정하지 못하면
    보수적 하한으로 넘어가지 않고 계산을 포기한다.
    """

    def test_stress_lowers_the_mortgage_limit(self) -> None:
        result = _run()
        best = result.best
        assert best is not None and best.option is not None

        # 같은 입력으로 스트레스만 빼고 직접 계산한 값보다 반드시 낮아야 한다.
        stressed_inputs = next(
            adaptation.inputs
            for adaptation in adapt_handoff_for_loan_max(
                route_product_candidates(
                    _candidates(),
                    user_facts={"age": 34, "is_overdraft_type": False},
                    as_of=_AS_OF,
                    registry=ProductRulePackRegistry((_PACK,)),
                ).forwardable[0],
                borrower=_BORROWER,
                policy_limits=PolicyLimits(
                    ltv_limit_amount=Decimal("320000000"),
                    dti_limit_amount=Decimal("395000000"),
                ),
                required_amount=Decimal("300000000"),
                months=360,
            )
            if adaptation.inputs is not None
            and adaptation.inputs.annual_rate == best.option.rate("avg")
        )
        assert stressed_inputs.dsr_annual_rate is None
        unstressed_amount = loan_max(**stressed_inputs.as_kwargs())  # type: ignore[arg-type]

        assert best.amount < unstressed_amount, (
            f"스트레스 적용 결과 {best.amount:,.0f}원이 미적용 "
            f"{unstressed_amount:,.0f}원보다 낮지 않습니다."
        )

    def test_capital_region_is_stressed_more_than_local(self) -> None:
        # 지방 0.75%p vs 수도권·규제지역 3.0%p — 같은 차주라도 한도가 달라진다.
        capital = _run(
            zone=RegulationZone.SPECULATION_OVERHEATED,
            is_capital_region=True,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
        )
        local = _run(
            zone=RegulationZone.NON_REGULATED,
            is_capital_region=False,
            housing_status=HousingStatus.NO_HOUSE,
        )
        assert capital.best is not None and local.best is not None
        assert capital.best.amount < local.best.amount

    def test_a_product_without_a_resolvable_stress_rate_is_not_calculated(self) -> None:
        # 전세대출('주담대 외')은 1차 출처를 확인하지 못해 미검증이다.
        jeonse_pack = ProductRulePack(
            product_name="KB스타 전세자금대출(SGI_서울보증보험)",
            category=ProductCategory.JEONSE_LOAN,
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
        base = {
            "source_type": "manual_pdf",
            "fin_prdt_nm": "KB스타 전세자금대출(SGI_서울보증보험)",
            "loan_lmt": (
                "최소 5백만원 이상 최대 5억원 이하 (임차보증금액의 80% 이내, "
                "1주택자 최대 3억원 이내, 규제지역 1주택자 2억원 제한)"
            ),
        }
        candidate = ProductCandidate(
            product_name="KB스타 전세자금대출(SGI_서울보증보험)",
            base_data=base,
            option_list=_OPTIONS,
        )
        facts = {
            "age": 34,
            "owned_house_count": 0,
            "is_regulated_region": True,
            "lease_deposit": Decimal("400000000"),
        }

        blocked = simulate_loan_options(
            _request(user_facts=facts),
            [candidate],
            registry=ProductRulePackRegistry((jeonse_pack,)),
        )
        assert blocked.executable == ()
        assert blocked.unresolved
        assert "stress_dsr_rate" in blocked.unresolved[0].missing_inputs

        # 미검증 사용을 명시적으로 허용하면 계산된다.
        allowed = simulate_loan_options(
            _request(user_facts=facts, allow_unverified_regulation=True),
            [candidate],
            registry=ProductRulePackRegistry((jeonse_pack,)),
        )
        assert allowed.executable

    def test_stress_source_is_recorded(self) -> None:
        result = _run()
        assert any("스트레스" in source for source in result.policy_sources)


class TestRegionFactsCannotContradictTheZone:
    """지역 구분의 근거는 하나여야 한다.

    `zone`은 지정 목록에서 나온 값이고 `user_facts`의 지역 키는 사람이 채운다.
    어긋나면 LTV는 규제지역 40%로 계산하면서 상품 한도는 비규제 3억을 쓰는
    자기모순이 생긴다. 요청의 값으로 덮어써 근거를 하나로 만든다.
    """

    def test_facts_are_overwritten_from_the_request(self) -> None:
        request = _request(
            user_facts={"age": 34, "is_regulated_region": False, "is_capital_region": False},
            zone=RegulationZone.SPECULATION_OVERHEATED,
            is_capital_region=True,
        )
        aligned = _align_region_facts(request)
        assert aligned["is_regulated_region"] is True
        assert aligned["is_capital_region"] is True

    def test_non_regulated_zone_clears_the_flag(self) -> None:
        request = _request(
            user_facts={"age": 34, "is_regulated_region": True},
            zone=RegulationZone.NON_REGULATED,
            is_capital_region=False,
        )
        aligned = _align_region_facts(request)
        assert aligned["is_regulated_region"] is False

    def test_other_facts_are_left_alone(self) -> None:
        request = _request(user_facts={"age": 34, "employment_months": 60})
        aligned = _align_region_facts(request)
        assert aligned["age"] == 34
        assert aligned["employment_months"] == 60

    def test_a_lie_in_the_facts_cannot_change_the_product_limit(self) -> None:
        facts = {
            "owned_house_count": 1,
            "lease_deposit": Decimal("500000000"),
            "is_regulated_region": False,  # 거짓말
        }
        honest = {**facts, "is_regulated_region": True}
        limits = {
            resolve_product_limit(
                "KB스타 전세자금대출(SGI_서울보증보험)",
                _align_region_facts(
                    _request(user_facts=f, zone=RegulationZone.SPECULATION_OVERHEATED)
                ),
            ).amount
            for f in (facts, honest)
        }
        assert limits == {Decimal("200000000")}


class TestBuildRequestForRegion:
    def test_a_regulated_code_fills_the_zone(self) -> None:
        request = build_request_for_region(
            region_code="11680",
            as_of=_AS_OF,
            borrower=_BORROWER,
            user_facts={"age": 34, "is_overdraft_type": False},
            house_price=Decimal("800000000"),
            housing_status=HousingStatus.NO_HOUSE,
            required_amount=Decimal("300000000"),
            months=360,
        )
        assert isinstance(request, LoanSimulationRequest)
        assert request.zone is RegulationZone.SPECULATION_OVERHEATED
        assert request.is_capital_region is True

    def test_a_local_code_fills_non_regulated(self) -> None:
        request = build_request_for_region(
            region_code="30200",
            as_of=_AS_OF,
            borrower=_BORROWER,
            user_facts={"age": 34, "is_overdraft_type": False},
            house_price=Decimal("800000000"),
            housing_status=HousingStatus.NO_HOUSE,
            required_amount=Decimal("300000000"),
            months=360,
        )
        assert isinstance(request, LoanSimulationRequest)
        assert request.zone is RegulationZone.NON_REGULATED
        assert request.is_capital_region is False

    def test_an_unresolvable_region_returns_the_reason_not_a_request(self) -> None:
        # 임의로 비규제로 채우면 LTV 70%가 적용돼 한도가 크게 과대평가된다.
        result = build_request_for_region(
            region_code="99999",
            as_of=_AS_OF,
            borrower=_BORROWER,
            user_facts={"age": 34},
            house_price=Decimal("800000000"),
            housing_status=HousingStatus.NO_HOUSE,
            required_amount=Decimal("300000000"),
            months=360,
        )
        assert isinstance(result, ResolvedRegion)
        assert not result.is_resolved
        assert result.note is not None


class TestDtiRegionComesFromTheSameRegionFacts:
    """DTI 지역 구분이 지역 사실의 **세 번째** 출처가 되면 안 된다.

    예전에는 `dti_region`이 기본값 "SEOUL" 문자열이라, 지역 코드로 요청을
    만들어도 대전 차주에게 서울 DTI 50%가 붙었다. 지방은 DTI 규제 대상이
    아니므로 그 상한은 애초에 존재하지 않는다.
    """

    def test_a_local_region_is_not_subject_to_dti(self) -> None:
        request = _request(
            zone=RegulationZone.NON_REGULATED,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            is_capital_region=False,
        )
        assert resolve_dti_region(request) is DtiRegion.NON_CAPITAL

        resolved = resolve_dti_ratio(DtiRegion.NON_CAPITAL, as_of=_AS_OF)
        assert resolved.ratio is None
        assert resolved.applies is False
        # "적용 대상 아님"은 "모름"이 아니다 — 계산을 막으면 안 된다.
        assert resolved.is_resolved is True

    def test_a_local_borrower_can_still_be_computed(self) -> None:
        result = _run(
            zone=RegulationZone.NON_REGULATED,
            housing_status=HousingStatus.NO_HOUSE,
            is_capital_region=False,
        )
        assert result.is_resolved
        assert result.executable, "DTI 비대상 지역이라고 계산이 막히면 안 된다"

    def test_capital_without_a_code_falls_back_to_the_stricter_seoul_ratio(self) -> None:
        # 수도권인 것만 알고 서울인지 모르면 더 엄격한 쪽으로 물러선다.
        assert resolve_dti_region(_request(is_capital_region=True)) is DtiRegion.SEOUL
        seoul = resolve_dti_ratio(DtiRegion.SEOUL, as_of=_AS_OF).ratio
        capital = resolve_dti_ratio(DtiRegion.CAPITAL_REGION, as_of=_AS_OF).ratio
        assert seoul is not None and capital is not None
        assert seoul.ratio < capital.ratio

    def test_a_contradiction_is_refused(self) -> None:
        request = _request(dti_region=DtiRegion.SEOUL, is_capital_region=False)
        with pytest.raises(ValueError, match="어긋납니다"):
            resolve_dti_region(request)

    def test_build_request_fills_dti_region_from_the_code(self) -> None:
        common: dict[str, object] = {
            "borrower": _BORROWER,
            "user_facts": {"age": 34, "is_overdraft_type": False},
            "house_price": Decimal("800000000"),
            "housing_status": HousingStatus.NO_HOUSE,
            "required_amount": Decimal("300000000"),
            "months": 360,
        }
        by_code = {
            "11680": DtiRegion.SEOUL,  # 강남구
            "41135": DtiRegion.CAPITAL_REGION,  # 성남시 분당구
            "30200": DtiRegion.NON_CAPITAL,  # 대전 유성구
        }
        for code, expected in by_code.items():
            request = build_request_for_region(region_code=code, as_of=_AS_OF, **common)
            assert isinstance(request, LoanSimulationRequest)
            assert request.dti_region is expected, code


class TestLtvAndDtiOnlyBindMortgages:
    """LTV·DTI는 주택담보대출 규제다.

    신용대출·전세대출에 주택가격 기반 상한을 씌우면 "싼 집을 사면 신용대출
    한도가 줄어든다"는, 현실에 없는 규칙이 만들어진다. 예전에는 1.5억 주택을
    사는 차주의 신용대출 한도가 6천만원(=1.5억×40%)으로 잘렸다.
    """

    @staticmethod
    def _credit_run(house_price: str):
        pack = ProductRulePack(
            product_name="KB 신용대출",
            category=ProductCategory.CREDIT_LOAN,
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
        base = {
            "source_type": "manual_pdf",
            "fin_prdt_nm": "KB 신용대출",
            "loan_lmt": "최대 3억원 이내",
        }
        options = (
            {
                "fin_prdt_nm": "KB 신용대출",
                "mrtg_type_nm": "신용",
                "rpay_type_nm": "분할상환방식",
                "lend_rate_type_nm": "변동금리",
                "lend_rate_min": 5.0,
                "lend_rate_max": 5.0,
                "lend_rate_avg": 5.0,
            },
        )
        request = _request(
            house_price=Decimal(house_price),
            required_amount=Decimal("200000000"),
            credit_loan_balance=Decimal("0"),
        )
        return simulate_loan_options(
            request,
            [ProductCandidate(product_name="KB 신용대출", base_data=base, option_list=options)],
            registry=ProductRulePackRegistry((pack,)),
        )

    def test_the_house_price_does_not_shrink_a_credit_loan(self) -> None:
        expensive = self._credit_run("800000000")
        cheap = self._credit_run("60000000")

        assert expensive.best is not None and cheap.best is not None
        # 8억 주택의 LTV 한도는 3.2억, 6천만원 주택은 2,400만원이다. 신용대출이
        # LTV에 걸리면 두 결과가 크게 달라진다.
        assert cheap.ltv is not None and cheap.ltv.amount == Decimal("24000000")
        assert cheap.best.amount == expensive.best.amount
        assert cheap.best.amount > Decimal("24000000")

    def test_a_mortgage_is_still_bound_by_ltv(self) -> None:
        # 반대 방향도 고정한다 — 주담대에서 LTV를 빼 버리면 이 검사가 깨진다.
        result = _run(house_price=Decimal("300000000"))
        assert result.ltv is not None and result.ltv.amount == Decimal("120000000")
        assert result.best is not None
        assert result.best.amount <= Decimal("120000000")
