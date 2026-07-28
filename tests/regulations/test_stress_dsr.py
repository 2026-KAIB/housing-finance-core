from datetime import date
from decimal import Decimal

import pytest

from app.regulations.stress_dsr import (
    CREDIT_LOAN_STRESS_THRESHOLD,
    StressLoanKind,
    StressRate,
    StressRegion,
    get_stress_rate,
    resolve_stress_region,
    stressed_annual_rate,
)

_TODAY = date(2026, 7, 28)


class TestRegionResolution:
    """스트레스 금리의 지역 구분은 LTV의 규제지역 구분과 기준이 다르다."""

    def test_capital_region_counts_even_when_not_regulated(self) -> None:
        region = resolve_stress_region(is_capital_region=True, is_regulated_region=False)
        assert region is StressRegion.CAPITAL_OR_REGULATED

    def test_regulated_region_counts_even_outside_the_capital_area(self) -> None:
        region = resolve_stress_region(is_capital_region=False, is_regulated_region=True)
        assert region is StressRegion.CAPITAL_OR_REGULATED

    def test_neither_is_local(self) -> None:
        region = resolve_stress_region(is_capital_region=False, is_regulated_region=False)
        assert region is StressRegion.LOCAL


class TestMortgageRates:
    def test_capital_or_regulated_is_three_percent(self) -> None:
        rate = get_stress_rate(
            StressRegion.CAPITAL_OR_REGULATED, StressLoanKind.MORTGAGE, as_of=_TODAY
        )
        assert rate is not None
        assert rate.rate == Decimal("0.030")

    def test_local_is_zero_point_seven_five_percent(self) -> None:
        rate = get_stress_rate(StressRegion.LOCAL, StressLoanKind.MORTGAGE, as_of=_TODAY)
        assert rate is not None
        assert rate.rate == Decimal("0.0075")

    def test_three_percent_does_not_apply_before_its_effective_date(self) -> None:
        # 수도권·규제지역 3.0%는 2025-10-16 시행이다. 그 이전 구간의 값은
        # 1차 출처를 확인하지 못해 표에 없으므로 조회되지 않아야 한다.
        assert (
            get_stress_rate(
                StressRegion.CAPITAL_OR_REGULATED,
                StressLoanKind.MORTGAGE,
                as_of=date(2025, 10, 15),
            )
            is None
        )


class TestCreditLoanThreshold:
    """신용대출은 잔액 1억원 초과 시에만 스트레스 금리가 붙는다."""

    def test_balance_above_the_threshold_gets_the_rate(self) -> None:
        rate = get_stress_rate(
            StressRegion.LOCAL,
            StressLoanKind.CREDIT,
            as_of=_TODAY,
            credit_loan_balance=CREDIT_LOAN_STRESS_THRESHOLD + Decimal("1"),
        )
        assert rate is not None
        assert rate.rate == Decimal("0.015")

    def test_balance_at_or_below_the_threshold_is_a_confirmed_zero(self) -> None:
        # 0은 "적용 안 됨"이 확정된 상태다 — "모름"과 구분해야 한다.
        rate = get_stress_rate(
            StressRegion.LOCAL,
            StressLoanKind.CREDIT,
            as_of=_TODAY,
            credit_loan_balance=CREDIT_LOAN_STRESS_THRESHOLD,
        )
        assert rate is not None
        assert rate.rate == Decimal("0")

    def test_unknown_balance_is_unknown_not_zero(self) -> None:
        # 0으로 뭉개면 스트레스가 빠져 한도가 과대평가된다.
        assert (
            get_stress_rate(StressRegion.LOCAL, StressLoanKind.CREDIT, as_of=_TODAY) is None
        )


class TestUnverifiedRatesAreWithheld:
    def test_other_loan_kinds_need_an_explicit_opt_in(self) -> None:
        # 전세대출 등 '주담대 외' 개별 취급은 1차 출처로 확인하지 못했다.
        assert get_stress_rate(StressRegion.LOCAL, StressLoanKind.OTHER, as_of=_TODAY) is None

        allowed = get_stress_rate(
            StressRegion.LOCAL, StressLoanKind.OTHER, as_of=_TODAY, allow_unverified=True
        )
        assert allowed is not None
        assert allowed.verified is False


class TestStressedRate:
    def test_add_on_is_added_to_the_actual_rate(self) -> None:
        stress = StressRate(
            rate=Decimal("0.03"), source="test", effective_from=date(2025, 10, 16)
        )
        assert stressed_annual_rate(Decimal("0.04"), stress) == Decimal("0.07")

    def test_negative_actual_rate_is_rejected(self) -> None:
        stress = StressRate(
            rate=Decimal("0.03"), source="test", effective_from=date(2025, 10, 16)
        )
        with pytest.raises(ValueError, match="annual_rate"):
            stressed_annual_rate(Decimal("-0.01"), stress)
