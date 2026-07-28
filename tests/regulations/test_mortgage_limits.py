from datetime import date
from decimal import Decimal

import pytest

from app.engines.loan.formulas import pmt
from app.regulations.mortgage_limits import (
    HousingStatus,
    RegulationZone,
    get_ltv_ratio,
    get_mortgage_hard_cap,
    resolve_dti_limit_amount,
    resolve_ltv_limit_amount,
)

_TODAY = date(2026, 7, 28)


class TestLtvRatioLookup:
    def test_regulated_zone_is_forty_percent(self) -> None:
        ratio = get_ltv_ratio(
            RegulationZone.SPECULATION_OVERHEATED, HousingStatus.NO_HOUSE, as_of=_TODAY
        )
        assert ratio is not None
        assert ratio.ratio == Decimal("0.40")

    def test_non_regulated_zone_is_seventy_percent(self) -> None:
        ratio = get_ltv_ratio(RegulationZone.NON_REGULATED, HousingStatus.NO_HOUSE, as_of=_TODAY)
        assert ratio is not None
        assert ratio.ratio == Decimal("0.70")

    def test_additional_purchase_by_multi_house_owner_is_prohibited(self) -> None:
        ratio = get_ltv_ratio(
            RegulationZone.SPECULATION_OVERHEATED, HousingStatus.MULTI_HOUSE, as_of=_TODAY
        )
        assert ratio is not None
        assert ratio.ratio == Decimal("0")

    def test_unverified_ratio_is_withheld_by_default(self) -> None:
        # 비규제지역 생애최초 80%는 6·27의 반대해석이라 1차 출처가 없다.
        assert (
            get_ltv_ratio(
                RegulationZone.NON_REGULATED, HousingStatus.FIRST_HOME_BUYER, as_of=_TODAY
            )
            is None
        )
        allowed = get_ltv_ratio(
            RegulationZone.NON_REGULATED,
            HousingStatus.FIRST_HOME_BUYER,
            as_of=_TODAY,
            allow_unverified=True,
        )
        assert allowed is not None
        assert allowed.verified is False

    def test_ratio_is_not_returned_before_its_effective_date(self) -> None:
        assert (
            get_ltv_ratio(
                RegulationZone.SPECULATION_OVERHEATED,
                HousingStatus.NO_HOUSE,
                as_of=date(2026, 6, 30),
            )
            is None
        )


class TestHardCapTiers:
    @pytest.mark.parametrize(
        ("house_price", "expected"),
        [
            (Decimal("800000000"), Decimal("600000000")),
            (Decimal("1500000000"), Decimal("600000000")),
            (Decimal("1500000001"), Decimal("400000000")),
            (Decimal("2500000000"), Decimal("400000000")),
            (Decimal("3000000000"), Decimal("200000000")),
        ],
    )
    def test_tiers(self, house_price: Decimal, expected: Decimal) -> None:
        assert get_mortgage_hard_cap(house_price, as_of=_TODAY) == expected

    def test_not_applicable_before_effective_date(self) -> None:
        assert get_mortgage_hard_cap(Decimal("800000000"), as_of=date(2025, 10, 15)) is None


class TestLtvLimitAmount:
    def test_ltv_ratio_binds_when_it_is_lower(self) -> None:
        # 비규제·지방: 10억 × 70% = 7억. 구간별 한도(6억)는 수도권·규제지역
        # 전용이므로 걸리지 않는다.
        resolved = resolve_ltv_limit_amount(
            house_price=Decimal("1000000000"),
            zone=RegulationZone.NON_REGULATED,
            status=HousingStatus.NO_HOUSE,
            is_capital_region=False,
            as_of=_TODAY,
        )
        assert resolved.amount == Decimal("700000000")
        assert resolved.binding_reason == "LTV 70%"

    def test_hard_cap_binds_in_the_capital_region(self) -> None:
        # 같은 10억 주택이라도 수도권이면 6억 상한이 씌워진다.
        resolved = resolve_ltv_limit_amount(
            house_price=Decimal("1000000000"),
            zone=RegulationZone.NON_REGULATED,
            status=HousingStatus.NO_HOUSE,
            is_capital_region=True,
            as_of=_TODAY,
        )
        assert resolved.amount == Decimal("600000000")
        assert resolved.binding_reason is not None
        assert "구간별 한도" in resolved.binding_reason

    def test_regulated_zone_forty_percent(self) -> None:
        resolved = resolve_ltv_limit_amount(
            house_price=Decimal("1000000000"),
            zone=RegulationZone.SPECULATION_OVERHEATED,
            status=HousingStatus.NO_HOUSE,
            is_capital_region=True,
            as_of=_TODAY,
        )
        # 10억 × 40% = 4억. 6억 상한보다 낮으므로 LTV가 구속한다.
        assert resolved.amount == Decimal("400000000")
        assert resolved.binding_reason == "LTV 40%"

    def test_expensive_house_hits_the_two_hundred_million_tier(self) -> None:
        resolved = resolve_ltv_limit_amount(
            house_price=Decimal("3000000000"),
            zone=RegulationZone.SPECULATION_OVERHEATED,
            status=HousingStatus.NO_HOUSE,
            is_capital_region=True,
            as_of=_TODAY,
        )
        # 30억 × 40% = 12억이지만 25억 초과 구간 한도 2억이 이긴다.
        assert resolved.amount == Decimal("200000000")

    def test_unknown_combination_returns_no_amount(self) -> None:
        resolved = resolve_ltv_limit_amount(
            house_price=Decimal("1000000000"),
            zone=RegulationZone.NON_REGULATED,
            status=HousingStatus.FIRST_HOME_BUYER,
            is_capital_region=False,
            as_of=_TODAY,
        )
        assert resolved.amount is None
        assert resolved.missing_inputs == ("ltv_ratio",)


class TestRegulatedZonesShareTheSameLtv:
    """26·6·30은 투기과열지구와 조정대상지역을 "규제지역"으로 묶어 다루며
    둘에 다른 LTV를 적용하지 않는다. 조정대상지역만 50%로 남아 있던 것은 오류다."""

    @pytest.mark.parametrize(
        "status",
        [HousingStatus.NO_HOUSE, HousingStatus.ONE_HOUSE_DISPOSAL_PLEDGED],
    )
    def test_both_regulated_zones_are_forty_percent_from_july_2026(
        self, status: HousingStatus
    ) -> None:
        for zone in (RegulationZone.SPECULATION_OVERHEATED, RegulationZone.ADJUSTMENT_TARGET):
            ratio = get_ltv_ratio(zone, status, as_of=date(2026, 7, 1))
            assert ratio is not None, zone
            assert ratio.ratio == Decimal("0.40"), zone
            assert ratio.verified is True, zone

    def test_first_home_buyer_keeps_the_relaxed_seventy_percent(self) -> None:
        for zone in (RegulationZone.SPECULATION_OVERHEATED, RegulationZone.ADJUSTMENT_TARGET):
            ratio = get_ltv_ratio(zone, HousingStatus.FIRST_HOME_BUYER, as_of=date(2026, 7, 1))
            assert ratio is not None, zone
            assert ratio.ratio == Decimal("0.70"), zone

    def test_the_superseded_fifty_percent_stops_applying_on_the_effective_date(self) -> None:
        # 낡은 값이 새 대책 이후에도 계속 조회되던 것이 이 이력 구조를 만든 이유다.
        before = get_ltv_ratio(
            RegulationZone.ADJUSTMENT_TARGET,
            HousingStatus.NO_HOUSE,
            as_of=date(2026, 6, 30),
            allow_unverified=True,
        )
        assert before is not None
        assert before.ratio == Decimal("0.50")
        assert before.verified is False

        after = get_ltv_ratio(
            RegulationZone.ADJUSTMENT_TARGET,
            HousingStatus.NO_HOUSE,
            as_of=date(2026, 7, 1),
            allow_unverified=True,
        )
        assert after is not None
        assert after.ratio == Decimal("0.40")

    def test_grandfathered_borrower_can_be_priced_at_the_earlier_date(self) -> None:
        # 경과규정: 6/30까지 신청·계약을 마친 차주는 종전 규정을 적용받는다.
        # `as_of`에 그 기준일을 넘기면 이력에서 당시 값이 나온다.
        grandfathered = get_ltv_ratio(
            RegulationZone.ADJUSTMENT_TARGET,
            HousingStatus.NO_HOUSE,
            as_of=date(2026, 6, 30),
            allow_unverified=True,
        )
        current = get_ltv_ratio(
            RegulationZone.ADJUSTMENT_TARGET, HousingStatus.NO_HOUSE, as_of=_TODAY
        )
        assert grandfathered is not None and current is not None
        assert grandfathered.ratio > current.ratio


class TestDtiLimitAmount:
    def test_resulting_principal_repays_exactly_the_allowed_annual_amount(self) -> None:
        # 연소득 6천만, DTI 50%, 기타부채 연 이자 300만원
        # → 신규 대출에 허용되는 연 원리금 = 3,000만 − 300만 = 2,700만원
        resolved = resolve_dti_limit_amount(
            annual_income=Decimal("60000000"),
            dti_ratio=Decimal("0.50"),
            other_annual_interest=Decimal("3000000"),
            annual_rate=Decimal("0.04"),
            months=360,
        )
        assert resolved.amount is not None
        annual_payment = pmt(resolved.amount, Decimal("0.04"), 360) * 12
        assert abs(annual_payment - Decimal("27000000")) < Decimal("1")

    def test_zero_when_existing_interest_already_exhausts_the_ratio(self) -> None:
        resolved = resolve_dti_limit_amount(
            annual_income=Decimal("50000000"),
            dti_ratio=Decimal("0.50"),
            other_annual_interest=Decimal("30000000"),
            annual_rate=Decimal("0.04"),
            months=360,
        )
        # 0원은 "모름"이 아니라 실제 한도가 0이라는 뜻이다.
        assert resolved.amount == Decimal("0")

    def test_zero_income_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            resolve_dti_limit_amount(
                annual_income=Decimal("0"),
                dti_ratio=Decimal("0.50"),
                other_annual_interest=Decimal("0"),
                annual_rate=Decimal("0.04"),
                months=360,
            )


class TestDtiInputValidation:
    """잘못된 입력은 조용히 큰 한도로 흘러나오지 말고 즉시 걸려야 한다."""

    _BASE = {
        "annual_income": Decimal("60000000"),
        "dti_ratio": Decimal("0.5"),
        "other_annual_interest": Decimal("0"),
        "annual_rate": Decimal("0.04"),
        "months": 360,
    }

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("annual_income", Decimal("0")),
            ("annual_income", Decimal("-60000000")),
            ("dti_ratio", Decimal("-0.5")),
            ("dti_ratio", Decimal("1.5")),
            ("other_annual_interest", Decimal("-1000000")),
            ("annual_rate", Decimal("-0.04")),
            ("months", 0),
            ("months", -12),
        ],
    )
    def test_invalid_input_raises(self, field_name: str, value: object) -> None:
        with pytest.raises(ValueError, match=field_name):
            resolve_dti_limit_amount(**{**self._BASE, field_name: value})  # type: ignore[arg-type]

    def test_validation_runs_before_the_zero_allowance_shortcut(self) -> None:
        # 기존 이자만으로 DTI를 소진해 0원이 나오는 경우에도, 금리·기간이
        # 잘못됐다면 0원 결과 뒤에 오류가 묻히면 안 된다.
        with pytest.raises(ValueError, match="months"):
            resolve_dti_limit_amount(
                annual_income=Decimal("60000000"),
                dti_ratio=Decimal("0.5"),
                other_annual_interest=Decimal("50000000"),
                annual_rate=Decimal("0.04"),
                months=0,
            )

    def test_a_valid_boundary_ratio_is_accepted(self) -> None:
        # 0과 1은 유효 범위의 경계이므로 막으면 안 된다.
        assert resolve_dti_limit_amount(**{**self._BASE, "dti_ratio": Decimal("0")}).amount == 0
        assert resolve_dti_limit_amount(**{**self._BASE, "dti_ratio": Decimal("1")}).amount > 0
