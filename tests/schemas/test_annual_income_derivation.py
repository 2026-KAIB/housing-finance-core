"""연소득을 월소득에서 파생한다.

DSR 분모는 **금융사 인정소득**이고, 마이데이터가 주는 월소득은 세후 실수령이다
(`mydata_design.md` §9). 둘은 다르며 인정소득은 따로 받는 것이 정확하다 — 설계서도
그 항목을 "합의 필요"로 표시해 두었다.

그 전까지는 월소득 × 12로 파생한다. 여기서 고정하는 것은 **방향**이다: 파생값은
인정소득보다 작고, 소득이 작으면 DSR이 커져 한도가 작게 나온다. 과소평가는 안전한
방향이므로(§22.3) 이 파생을 쓸 수 있다. 반대 방향이면 쓸 수 없다.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.property import PropertySearchCriteria
from app.schemas.property_affordability import PropertyAffordabilitySearchRequest
from app.schemas.simulation import (
    DERIVED_ANNUAL_INCOME_NOTE,
    AnnualIncomeSource,
    FinancialSnapshot,
    HousingGoal,
    SimulationInput,
    UserProfile,
)

_MONTHLY = Decimal("5000000")


def _payload(annual_income: Decimal | None = None) -> SimulationInput:
    return SimulationInput(
        profile=UserProfile(age=34, annual_income=annual_income),
        housing_goal=HousingGoal(
            target_amount=Decimal("300000000"),
            target_date=date(2028, 8, 1),
            region_code="11650",
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=_MONTHLY,
            monthly_expense=Decimal("2000000"),
            liquid_assets=Decimal("50000000"),
        ),
    )


def test_a_missing_annual_income_is_derived_from_the_monthly_one() -> None:
    payload = _payload()

    assert payload.resolved_annual_income == _MONTHLY * 12
    assert payload.annual_income_source is AnnualIncomeSource.DERIVED_FROM_MONTHLY


def test_a_supplied_annual_income_is_never_overwritten() -> None:
    """인정소득을 받았으면 그것이 사실이다. 파생값이 그 답을 덮으면 안 된다."""
    payload = _payload(Decimal("72000000"))

    assert payload.resolved_annual_income == Decimal("72000000")
    assert payload.annual_income_source is AnnualIncomeSource.PROVIDED


def test_the_derived_value_is_never_larger_than_a_realistic_recognised_income() -> None:
    """방향이 이 파생의 근거다.

    월소득은 세후 실수령이고 인정소득은 보통 세전이라, 12를 곱해도 인정소득에
    못 미친다. 소득을 작게 잡으면 DSR이 커져 한도가 **작게** 나온다.

    이 검사는 그 관계를 숫자로 못 박는다 — 파생값이 세전 추정보다 크면 방향이
    뒤집혀 한도가 부푼다.
    """
    payload = _payload()
    derived = payload.resolved_annual_income

    # 세후 실수령을 세전으로 되돌리면 반드시 더 커진다(세율이 0보다 크므로).
    gross_estimate = _MONTHLY * 12 / Decimal("0.85")
    assert derived < gross_estimate


def test_the_derivation_is_recorded_as_an_assumption() -> None:
    """숫자만 내보내면 근거 없는 확언이 된다(§20)."""
    assert "월소득 × 12" in DERIVED_ANNUAL_INCOME_NOTE
    assert "클 수 있습니다" in DERIVED_ANNUAL_INCOME_NOTE


def test_zero_income_is_still_zero_not_an_error() -> None:
    """소득 0은 "모름"이 아니라 확정된 0이다. 파생이 그 사실을 바꾸지 않는다."""
    payload = SimulationInput(
        profile=UserProfile(age=34),
        housing_goal=HousingGoal(
            target_amount=Decimal("300000000"),
            target_date=date(2028, 8, 1),
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal(0),
            monthly_expense=Decimal(0),
            liquid_assets=Decimal(0),
        ),
    )

    assert payload.resolved_annual_income == Decimal(0)


@pytest.mark.parametrize("annual", [None, Decimal("60000000")])
def test_the_property_flow_uses_the_same_rule(annual: Decimal | None) -> None:
    """두 진입점이 같은 값을 다르게 계산하면 두 화면이 다른 한도를 보여준다."""
    request = PropertyAffordabilitySearchRequest(
        criteria=PropertySearchCriteria(),
        profile=UserProfile(age=34, annual_income=annual),
        financial_snapshot=FinancialSnapshot(
            monthly_income=_MONTHLY,
            monthly_expense=Decimal("2000000"),
            liquid_assets=Decimal("50000000"),
        ),
    )

    assert request.resolved_annual_income == _payload(annual).resolved_annual_income
    assert request.annual_income_source is _payload(annual).annual_income_source
