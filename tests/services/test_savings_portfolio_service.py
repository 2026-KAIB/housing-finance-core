"""예·적금 배선: ``SimulationInput`` → 포트폴리오 → ``SimulationResult``.

고정하는 불변식:
1. 확정할 수 없는 값을 만들어 넣지 않는다 — 없으면 ``NOT_RUN`` + 결측.
2. 모르는 값의 기본은 **수익이 낮아지는 쪽**이다(대출과 방향이 반대).
3. 후보 0건과 "가입 가능한 상품이 없음"을 가른다.
4. 예산은 현금흐름 진단에서 파생하고, 파생한 사실을 가정으로 남긴다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.engines.savings.portfolio_models import SavingsPortfolioStatus
from app.regulations.mortgage_limits import HousingStatus
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SavingsRequestInput,
    SectionRunStatus,
    SimulationInput,
    UserProfile,
)
from app.services.cashflow_diagnosis import diagnose_cashflow
from app.services.savings_portfolio import (
    GENERAL_INTEREST_TAX_RATE,
    SavingsPortfolioBlocked,
    SavingsPortfolioOutcome,
    simulate_savings_portfolio,
)
from app.services.simulation_orchestrator import run_simulation

AS_OF = date(2026, 7, 31)
CALCULATED_AT = datetime(2026, 7, 31, 9, tzinfo=UTC)
SIMULATION_ID = UUID("2b1f0c8e-9a44-4d51-8f26-7c0d3e5a9b17")

# 실제 Rule Pack이 있는 상품이라야 상품정책 판정이 돈다.
TERM_DEPOSIT = "일반정기예금"
INSTALLMENT = "KB반려행복적금"


def _deposit_candidate() -> ProductCandidate:
    return ProductCandidate(
        product_name=TERM_DEPOSIT,
        base_data={
            "product_id": 9001,
            "fin_co_no": "0010001",
            "kor_co_nm": "국민은행",
            "fin_prdt_nm": TERM_DEPOSIT,
            "category_code": "TERM_DEPOSIT",
            "mtrt_int": "만기 후 1년 이내: 기본금리의 50%",
            "max_limit": None,
            "rate_beyond_contract_max": None,
            "extra_rate_info": None,
        },
        option_list=(
            {
                "fin_prdt_nm": TERM_DEPOSIT,
                "save_trm": 24,
                "intr_rate_type": "S",
                "intr_rate_type_nm": "단리",
                "intr_rate": 3.0,
                "intr_rate2": 3.4,
            },
        ),
    )


def _profile() -> UserProfile:
    return UserProfile(age=34, annual_income=Decimal("60000000"), is_first_home_buyer=True)


def _payload(savings_request: SavingsRequestInput | None) -> SimulationInput:
    return SimulationInput(
        profile=_profile(),
        housing_goal=HousingGoal(
            target_amount=Decimal("500000000"),
            target_date=date(2028, 7, 31),
            region_code="11680",
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            # 예금자보호 한도(1억) 아래로 둔다. 넘으면 한 곳에 다 넣을 수 없어
            # 배분 자체가 막히는데, 그건 이 픽스처가 확인하려는 것이 아니다.
            liquid_assets=Decimal("60000000"),
            monthly_debt_payment=Decimal("300000"),
            emergency_reserve=Decimal("12000000"),
        ),
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal("1800000"),
        ),
        savings_request=savings_request,
    )


def _run(payload: SimulationInput, candidates=()):
    return simulate_savings_portfolio(
        payload,
        candidates,
        as_of=AS_OF,
        cashflow_result=diagnose_cashflow(payload, as_of=AS_OF),
    )


# --------------------------------------------------------------------------
# 실행하지 않는 경우
# --------------------------------------------------------------------------


def test_without_a_savings_request_the_section_is_not_run() -> None:
    outcome = _run(_payload(None), (_deposit_candidate(),))

    assert isinstance(outcome, SavingsPortfolioBlocked)
    assert outcome.missing_inputs == ("savings_request",)


def test_zero_candidates_is_not_the_same_as_no_eligible_product() -> None:
    outcome = _run(_payload(SavingsRequestInput()), ())

    assert isinstance(outcome, SavingsPortfolioBlocked)
    assert outcome.missing_inputs == ("savings_product_candidates",)
    assert any("후보 0건은" in reason for reason in outcome.reasons)


def test_an_unknown_deposit_protection_limit_stops_the_section() -> None:
    """보호 한도를 모르면 배분하지 않는다 — 넘겨 배분할 수 있다."""
    outcome = simulate_savings_portfolio(
        _payload(SavingsRequestInput()),
        (_deposit_candidate(),),
        as_of=date(1999, 1, 1),
        cashflow_result=diagnose_cashflow(_payload(None), as_of=AS_OF),
    )

    assert isinstance(outcome, SavingsPortfolioBlocked)
    assert outcome.missing_inputs == ("deposit_protection_limit",)


# --------------------------------------------------------------------------
# 실행되는 경우
# --------------------------------------------------------------------------


@pytest.fixture
def outcome() -> SavingsPortfolioOutcome:
    result = _run(_payload(SavingsRequestInput()), (_deposit_candidate(),))
    assert isinstance(result, SavingsPortfolioOutcome)
    return result


def test_a_portfolio_is_built_from_the_cashflow_budget(
    outcome: SavingsPortfolioOutcome,
) -> None:
    assert outcome.result.status in (
        SavingsPortfolioStatus.COMPLETE,
        SavingsPortfolioStatus.PARTIAL,
    )
    assert outcome.result.allocations
    assert outcome.result.expected_maturity_amount > 0
    assert outcome.validation.valid


def test_derived_budgets_are_recorded_as_assumptions(
    outcome: SavingsPortfolioOutcome,
) -> None:
    joined = "\n".join(outcome.assumptions)

    assert "월 주택저축 가능액으로 파생" in joined
    # 목돈이 대출 자기자본과 같은 돈이라는 사실을 문서가 밝혀야 한다.
    assert "자기자본으로 보는 것과 같은 돈" in joined
    assert "주택 목표 시점과 같다고" in joined


def test_unknown_preferences_lower_the_expected_return_not_raise_it(
    outcome: SavingsPortfolioOutcome,
) -> None:
    """대출과 방향이 반대다 — 모르면 수익이 낮아지는 쪽으로 둔다."""
    joined = "\n".join(outcome.assumptions)

    assert "우대금리를 달성하지 않는 것으로" in joined
    assert f"일반과세 {GENERAL_INTEREST_TAX_RATE * 100:.1f}%" in joined
    assert "0원으로 두었습니다" in joined


def test_unconfirmed_preferences_stay_in_missing_inputs(
    outcome: SavingsPortfolioOutcome,
) -> None:
    assert "existing_institution_deposits" in outcome.missing_inputs
    assert "liquidity_preference" in outcome.missing_inputs


def test_a_stated_bonus_probability_raises_the_expected_maturity(
    outcome: SavingsPortfolioOutcome,
) -> None:
    """우대 미달성 기본값이 실제로 보수적인지 뒤집어 확인한다."""
    optimistic = _run(
        _payload(SavingsRequestInput(bonus_achievement_probability=Decimal(1))),
        (_deposit_candidate(),),
    )

    assert isinstance(optimistic, SavingsPortfolioOutcome)
    assert optimistic.result.expected_maturity_amount > (
        outcome.result.expected_maturity_amount
    )


def test_an_explicit_budget_overrides_the_derived_one() -> None:
    outcome = _run(
        _payload(
            SavingsRequestInput(
                monthly_savings_budget=Decimal("500000"),
                lump_sum_budget=Decimal("10000000"),
            )
        ),
        (_deposit_candidate(),),
    )

    assert isinstance(outcome, SavingsPortfolioOutcome)
    assert outcome.result.lump_sum_allocated <= Decimal("10000000")
    assert not any("파생했습니다" in item for item in outcome.assumptions)


# --------------------------------------------------------------------------
# 오케스트레이터 연결
# --------------------------------------------------------------------------


def _simulate(payload: SimulationInput, savings_candidates=()):
    return run_simulation(
        payload,
        simulation_id=SIMULATION_ID,
        as_of=AS_OF,
        calculated_at=CALCULATED_AT,
        savings_candidates=savings_candidates,
    )


def test_the_simulation_result_carries_the_savings_section() -> None:
    result = _simulate(_payload(SavingsRequestInput()), (_deposit_candidate(),))

    section = result.savings_portfolio
    assert section.run_status is SectionRunStatus.COMPLETED
    assert section.result is not None
    assert section.result["allocations"]
    assert section.assumptions
    # 종합추천도 예·적금만으로 열린다 — 대출을 못 돌려도 저축 계획은 나와야 한다.
    assert result.recommendation.run_status is SectionRunStatus.COMPLETED


def test_a_blocked_savings_section_says_what_is_missing() -> None:
    result = _simulate(_payload(None), (_deposit_candidate(),))

    section = result.savings_portfolio
    assert section.run_status is SectionRunStatus.NOT_RUN
    assert "savings_request" in section.missing_inputs
    assert "savings_request" in result.missing_inputs


def test_a_caller_supplied_result_is_not_recalculated() -> None:
    """호출자가 결과를 넘겼으면 이 계층이 다시 계산하지 않는다."""
    first = _simulate(_payload(SavingsRequestInput()), (_deposit_candidate(),))
    assert first.savings_portfolio.result is not None

    reused = run_simulation(
        _payload(SavingsRequestInput()),
        simulation_id=SIMULATION_ID,
        as_of=AS_OF,
        calculated_at=CALCULATED_AT,
        savings_candidates=(),
        savings_portfolio_result=_run(
            _payload(SavingsRequestInput()), (_deposit_candidate(),)
        ).result,
    )

    # 후보를 안 넘겼는데도 결과가 살아 있다 — 다시 계산했다면 결측으로 막혔다.
    assert reused.savings_portfolio.run_status is SectionRunStatus.COMPLETED
    assert reused.savings_portfolio.result == first.savings_portfolio.result


# --------------------------------------------------------------------------
# 보고서 연결
# --------------------------------------------------------------------------


def test_the_report_form_does_not_count_the_deposit_principal_twice() -> None:
    """만기 수령액을 그대로 부족액에서 빼면 같은 돈을 두 번 센다.

    필요 대출금액이 이미 ``목표금액 − 유동자산``이라 예금에 넣은 목돈은
    자기자본으로 한 번 빠져 있다. 예금이 **새로 보태는** 것은 이자뿐이다.
    """
    from app.reports.context import build_report_ai_input
    from app.reports.templates.form import build_report_form

    result = _simulate(_payload(SavingsRequestInput()), (_deposit_candidate(),))
    facts = result.savings_portfolio.result
    assert facts is not None

    maturity = Decimal(str(facts["expected_maturity_amount"]))
    principal = Decimal(str(facts["lump_sum_allocated"]))
    assert principal > 0, "이 픽스처는 예금 배분이 있어야 의미가 있다"

    section = build_report_form(build_report_ai_input(result)).section(
        "shortfall_and_extension"
    )
    assert section is not None
    joined = "\n".join(section.figures)

    assert f"{int(maturity - principal):,}원" in joined
    assert f"{int(maturity):,}원" not in joined
    assert "두 번 세지 않습니다" in joined
