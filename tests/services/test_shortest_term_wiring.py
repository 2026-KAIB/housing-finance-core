"""요청 만기를 갚을 수 있는 가장 짧은 기간으로 대체한다.

여기서 고정하는 것은 세 가지다.

1. **줄여도 조달액이 깎이지 않는다.** 기간을 줄이면 월 상환액이 올라 한도가
   줄어들 수 있는데, 그러면 이자를 아끼려다 집을 못 사게 된다.
2. **모든 후보가 같은 기간을 쓴다.** 옵션마다 만기가 다르면 총비용을 나란히 둘
   수 없고, 추천 엔진이 같은 이유로 기간 일치를 요구한다.
3. **갚을 수 없으면 줄이지 않는다.** 그때는 기간이 아니라 금액이 문제다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.regulations.mortgage_limits import HousingStatus
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SimulationInput,
    UserProfile,
)
from app.services.simulation_orchestrator import run_simulation

_AS_OF = date(2026, 8, 3)
_CALCULATED_AT = datetime(2026, 8, 3, 9, tzinfo=UTC)
_SIMULATION_ID = UUID("0f9b21e4-4c1a-4d7f-9c3e-2b6a5d8e1f30")
_REQUESTED_MONTHS = 360

_MORTGAGE = ProductCandidate(
    product_name="KB 주택담보대출",
    base_data={
        "source_type": "manual_pdf",
        "fin_prdt_nm": "KB 주택담보대출",
        "loan_lmt": "담보조사가격 및 소득금액에 따른 대출가능금액 이내",
    },
    option_list=(
        {
            "fin_prdt_nm": "KB 주택담보대출",
            "mrtg_type_nm": "아파트",
            "rpay_type_nm": "분할상환방식",
            "lend_rate_type_nm": "변동금리",
            "lend_rate_min": 3.0,
            "lend_rate_max": 3.0,
            "lend_rate_avg": 3.0,
        },
        # 금리가 다른 두 번째 옵션. 후보마다 최단 기간이 갈리는 상황을 만든다.
        {
            "fin_prdt_nm": "KB 주택담보대출",
            "mrtg_type_nm": "아파트",
            "rpay_type_nm": "분할상환방식",
            "lend_rate_type_nm": "고정금리",
            "lend_rate_min": 5.5,
            "lend_rate_max": 5.5,
            "lend_rate_avg": 5.5,
        },
    ),
)


def _run(monthly_income: str, *, liquid_assets: str = "0"):
    income = Decimal(monthly_income)
    payload = SimulationInput(
        profile=UserProfile(
            age=34,
            annual_income=income * 12,
            is_first_home_buyer=True,
            region_code="11650",
        ),
        housing_goal=HousingGoal(
            target_amount=Decimal("300000000"),
            target_date=date(2028, 8, 1),
            region_code="11650",
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=income,
            monthly_expense=Decimal("3000000"),
            liquid_assets=Decimal(liquid_assets),
            monthly_debt_payment=Decimal(0),
        ),
        loan_request=LoanRequestInput(
            months=_REQUESTED_MONTHS,
            housing_status=HousingStatus.NO_HOUSE,
            monthly_essential_expense=Decimal("2500000"),
        ),
    )
    return run_simulation(
        payload,
        simulation_id=_SIMULATION_ID,
        as_of=_AS_OF,
        calculated_at=_CALCULATED_AT,
        loan_candidates=[_MORTGAGE],
    )


def _executable(result) -> list[dict]:
    return (result.loan_simulation.result or {}).get("executable") or []


def test_a_high_earner_gets_a_shorter_term_than_requested() -> None:
    """월소득 1,000만원이 360개월을 쓸 이유가 없다. 요청값은 상한으로만 쓴다."""
    rows = _executable(_run("10000000"))

    assert rows
    assert all(row["months"] < _REQUESTED_MONTHS for row in rows)


def test_shortening_never_reduces_the_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    """이자를 아끼려다 집을 못 사게 되면 안 된다.

    기간을 줄이면 월 상환액이 올라 한도가 깎일 수 있다. 기준을 **후보들의 최단
    기간 중 가장 긴 값**으로 잡는 이유가 이것이다 — 모든 후보가 그 기간에 자기
    목표액을 그대로 조달할 수 있다.

    대조군은 **요청 만기를 그대로 쓴 계산**이다. 단축 로직만 끄고 나머지는 같은
    경로로 돌려 두 조달액을 나란히 둔다.
    """
    shortened = _executable(_run("10000000"))
    assert shortened

    monkeypatch.setattr(
        "app.services.loan_simulation._common_serviceable_months",
        lambda _adaptations: _REQUESTED_MONTHS,
    )
    unshortened = _executable(_run("10000000"))
    assert unshortened
    assert all(row["months"] == _REQUESTED_MONTHS for row in unshortened)

    by_option = {
        (row["product_name"], row["annual_rate"]): Decimal(str(row["amount"]))
        for row in unshortened
    }
    for row in shortened:
        key = (row["product_name"], row["annual_rate"])
        assert Decimal(str(row["amount"])) == by_option[key], (
            f"{key}: 만기를 줄이면서 조달액이 깎였다"
        )


def test_every_candidate_shares_one_term() -> None:
    """옵션마다 만기가 다르면 총비용을 나란히 둘 수 없다."""
    rows = _executable(_run("10000000"))

    assert rows
    assert len({row["months"] for row in rows}) == 1


def test_the_common_term_serves_the_slowest_option() -> None:
    """금리가 높은 옵션이 못 갚는 기간으로 줄이면 그 후보의 한도가 조용히 깎인다.

    그래서 기준은 후보별 최단 기간의 **최댓값**이다.
    """
    rows = _executable(_run("10000000"))
    months = {row["months"] for row in rows}

    assert len(months) == 1
    # 금리 5.5% 옵션도 같은 기간으로 실행 가능해야 한다.
    assert any(Decimal(str(row["annual_rate"])) >= Decimal("0.05") for row in rows)


def test_the_recommendation_survives_the_new_term() -> None:
    """추천 엔진은 후보들의 기간이 **서로 같은지**를 본다.

    예전에는 "요청 기간과 같은가"를 봤다. 그 기준이면 계산이 만기를 줄인 순간
    추천 구간이 통째로 죽는다 — 실제로 그렇게 터졌다.
    """
    result = _run("10000000")

    assert result.recommendation.run_status.value == "COMPLETED"
    loan = (result.recommendation.result or {}).get("loan") or {}
    assert loan.get("primary") is not None
    # 줄어든 기간으로 계산됐는데도 추천이 살아 있다.
    assert _executable(result)[0]["months"] < _REQUESTED_MONTHS


def test_the_shortening_is_recorded_as_an_assumption() -> None:
    """숫자만 바뀌고 이유가 없으면 왜 만기가 줄었는지 알 수 없다."""
    rows = _executable(_run("10000000"))

    notes = [note for row in rows for note in (row.get("assumptions") or [])]
    assert any("만기를" in note and "줄였습니다" in note for note in notes)
    assert any("월 상환액은 그만큼 커집니다" in note for note in notes)


def test_a_borrower_who_cannot_repay_keeps_the_requested_term() -> None:
    """최대 기간으로도 못 갚으면 기간이 아니라 금액이 문제다.

    임의로 줄여 "가능"을 만들지 않는다.
    """
    rows = _executable(_run("2000000"))

    for row in rows:
        assert row["months"] == _REQUESTED_MONTHS


@pytest.mark.parametrize("income", ["10000000", "7000000", "5000000"])
def test_a_lower_income_needs_a_longer_term(income: str) -> None:
    """소득이 낮을수록 같은 금액을 더 오래 갚아야 한다."""
    rows = _executable(_run(income))

    assert rows
    assert rows[0]["months"] <= _REQUESTED_MONTHS
