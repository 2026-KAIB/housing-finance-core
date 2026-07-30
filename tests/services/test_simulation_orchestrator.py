"""오케스트레이터가 모르는 값을 느슨한 쪽으로 확정하지 않는지 검증한다.

이 저장소에서 반복해 나온 대출 쪽 결함은 거의 전부 **"모르는 값이 조용히 가장
느슨한 쪽으로 확정되는"** 형태였다(지역 미확인 시 비규제, 스트레스 0 대체,
뒤 규칙 `True` 확정). 새로 생긴 HTTP 경계가 같은 실수를 다시 만들지 않도록
결측 경로를 여기서 고정한다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from app.regulations.mortgage_limits import HousingStatus
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SimulationInput,
    UserProfile,
)
from app.services.loan_simulation import resolve_dti_region
from app.services.simulation_orchestrator import build_loan_request, run_simulation

_AS_OF = date(2026, 7, 28)
_CALCULATED_AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
_SIMULATION_ID = UUID("0f9b21e4-4c1a-4d7f-9c3e-2b6a5d8e1f30")

_LOAN_SECTIONS = ("loan_simulation", "recommendation", "stress_test", "strategy_comparison")


def _loan_request(**overrides: object) -> LoanRequestInput:
    defaults: dict[str, object] = {
        "months": 360,
        "housing_status": HousingStatus.FIRST_HOME_BUYER,
        "monthly_essential_expense": Decimal("1800000"),
    }
    defaults.update(overrides)
    return LoanRequestInput(**defaults)  # type: ignore[arg-type]


def _payload(
    *,
    loan_request: LoanRequestInput | None = None,
    goal_region: str | None = "11680",
    profile_region: str | None = None,
) -> SimulationInput:
    return SimulationInput(
        profile=UserProfile(
            age=34,
            annual_income=Decimal("60000000"),
            is_first_home_buyer=True,
            region_code=profile_region,
        ),
        housing_goal=HousingGoal(
            target_amount=Decimal("500000000"),
            target_date=date(2028, 7, 30),
            region_code=goal_region,
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            liquid_assets=Decimal("150000000"),
            monthly_debt_payment=Decimal("300000"),
        ),
        loan_request=loan_request,
    )


def _run(payload: SimulationInput, *, as_of: date = _AS_OF, **kwargs: object):
    return run_simulation(
        payload,
        simulation_id=_SIMULATION_ID,
        as_of=as_of,
        calculated_at=_CALCULATED_AT,
        **kwargs,  # type: ignore[arg-type]
    )


def test_missing_loan_block_leaves_every_downstream_section_not_run() -> None:
    """만기·주택보유상태를 모르면 기본값으로 채우지 않고 계산을 시작하지 않는다."""
    result = _run(_payload())

    assert result.loan_simulation.missing_inputs == ("loan_request",)
    assert "loan_request" in result.missing_inputs
    for name in _LOAN_SECTIONS:
        assert getattr(result, name).run_status.value == "NOT_RUN"
        assert getattr(result, name).result is None


def test_unresolved_region_does_not_fall_back_to_non_regulated() -> None:
    """지역을 확정하지 못하면 비규제로 물러서지 않는다.

    비규제가 가장 느슨한 구분이라(LTV 70% vs 40%) 물러서면 한도가 과대평가된다.
    """
    result = _run(_payload(loan_request=_loan_request(), goal_region=None))

    assert result.loan_simulation.missing_inputs == ("regulation_region",)
    assert result.loan_simulation.run_status.value == "NOT_RUN"
    assert any("과대평가" in reason for reason in result.loan_simulation.reasons)


def test_expired_designation_list_blocks_a_non_regulated_conclusion() -> None:
    """지정 목록 유효기한을 넘긴 기준일에는 비규제라고 단정하지 않는다.

    목록에 없는 지역(대전)을 유효기한 뒤 기준일로 조회하면, 그 사이 새 고시가
    있었을 수 있으므로 확정 실패로 답해야 한다.
    """
    payload = _payload(loan_request=_loan_request(), goal_region="30110")

    inside, missing_inside, _, _ = build_loan_request(payload, as_of=date(2026, 7, 28))
    outside, missing_outside, _, _ = build_loan_request(payload, as_of=date(2026, 7, 30))

    assert inside is not None and missing_inside == ()
    assert outside is None
    assert missing_outside == ("regulation_region",)


def test_zero_candidates_is_reported_as_missing_not_as_no_eligible_product() -> None:
    """후보 0건과 "조건을 만족하는 상품이 없음"은 다른 상태다."""
    result = _run(_payload(loan_request=_loan_request()), loan_candidates=[])

    assert result.loan_simulation.missing_inputs == ("loan_product_candidates",)
    assert result.loan_simulation.run_status.value == "NOT_RUN"
    assert any("다른 상태" in reason for reason in result.loan_simulation.reasons)


def test_multi_house_does_not_invent_an_owned_house_count() -> None:
    """다주택은 "2채 이상"일 뿐이므로 정확한 채수를 만들어내지 않는다.

    2로 적으면 3채 차주를 통과시킬 수 있고, 그건 한도가 커지는 방향의 오류다.
    """
    request, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request(housing_status=HousingStatus.MULTI_HOUSE)),
        as_of=_AS_OF,
    )

    assert request is not None
    assert request.user_facts["owns_house"] is True
    assert "owned_house_count" not in request.user_facts


def test_one_house_and_no_house_do_set_a_known_count() -> None:
    """반대로 확정할 수 있는 채수는 채운다 — 모른다고 뭉개지도 않는다."""
    keeping, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request(housing_status=HousingStatus.ONE_HOUSE_KEEPING)),
        as_of=_AS_OF,
    )
    none_owned, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request(housing_status=HousingStatus.NO_HOUSE)),
        as_of=_AS_OF,
    )

    assert keeping is not None and keeping.user_facts["owned_house_count"] == 1
    assert none_owned is not None and none_owned.user_facts["owned_house_count"] == 0


def test_dti_region_distinguishes_seoul_from_the_rest_of_the_capital_area() -> None:
    """서울과 경기를 구분한다. 뭉개면 경기 차주에게 서울 50%가 붙는다."""
    seoul, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request(), goal_region="11680"),
        as_of=_AS_OF,
    )
    bundang, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request(), goal_region="41135"),
        as_of=_AS_OF,
    )

    assert seoul is not None and resolve_dti_region(seoul).value == "SEOUL"
    assert bundang is not None and resolve_dti_region(bundang).value == "CAPITAL_REGION"


def test_the_property_region_wins_over_the_residence_region() -> None:
    """규제지역은 목표 주택의 소재지가 정한다. 두 출처를 섞지 않는다."""
    request, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request(), goal_region="11680", profile_region="30110"),
        as_of=_AS_OF,
    )

    assert request is not None
    assert request.zone.value == "SPECULATION_OVERHEATED"


def test_derived_required_amount_records_that_costs_are_missing() -> None:
    """필요금액을 파생했으면 취득세·부대비용이 빠졌다는 가정을 남긴다."""
    _, _, _, assumptions = build_loan_request(
        _payload(loan_request=_loan_request()),
        as_of=_AS_OF,
    )
    _, _, _, explicit = build_loan_request(
        _payload(loan_request=_loan_request(required_amount=Decimal("300000000"))),
        as_of=_AS_OF,
    )

    assert any("취득세" in note for note in assumptions)
    assert not any("취득세" in note for note in explicit)


def test_derived_required_amount_never_exceeds_the_funding_gap() -> None:
    """파생 필요금액은 목표금액 − 유동자산이며 음수가 되지 않는다."""
    request, _, _, _ = build_loan_request(
        _payload(loan_request=_loan_request()),
        as_of=_AS_OF,
    )
    assert request is not None
    assert request.required_amount == Decimal("350000000")

    rich = _payload(loan_request=_loan_request())
    covered = rich.model_copy(
        update={
            "financial_snapshot": rich.financial_snapshot.model_copy(
                update={"liquid_assets": Decimal("900000000")}
            )
        }
    )
    request_covered, _, _, _ = build_loan_request(covered, as_of=_AS_OF)
    assert request_covered is not None
    assert request_covered.required_amount == Decimal(0)
