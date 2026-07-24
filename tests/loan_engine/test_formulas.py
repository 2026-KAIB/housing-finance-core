from decimal import Decimal

from app.engines.loan.formulas import buffer, dsr, pmt

TOLERANCE = Decimal("0.001")


def _within_tolerance(actual: Decimal, expected: Decimal) -> bool:
    return abs(actual - expected) / expected < TOLERANCE


def test_pmt_matches_golden_case() -> None:
    # DESIGN SSOT 부록 A-11: L=3억, 연 3.5%, n=360 -> 1,347,134원/월
    result = pmt(Decimal("300000000"), Decimal("0.035"), 360)

    assert _within_tolerance(result, Decimal("1347134"))


def test_pmt_with_zero_rate_is_flat_amortization() -> None:
    result = pmt(Decimal("120000000"), Decimal("0"), 120)

    assert result == Decimal("1000000")


def test_dsr_matches_golden_case_including_existing_debt() -> None:
    # DESIGN SSOT 부록 A-11/A-12: 연소득 6천만, 기존 연상환 600만,
    # 신규 PMT 1,347,134원/월(연 16,165,609) -> DSR 36.94%
    result = dsr(
        existing_annual_debt_service=Decimal("6000000"),
        new_annual_debt_service=Decimal("16165609"),
        annual_income=Decimal("60000000"),
    )

    assert _within_tolerance(result, Decimal("0.3694"))


def test_dsr_excludes_nothing_when_no_existing_debt() -> None:
    result = dsr(
        existing_annual_debt_service=Decimal("0"),
        new_annual_debt_service=Decimal("12000000"),
        annual_income=Decimal("60000000"),
    )

    assert result == Decimal("0.2")


def test_buffer_uses_floor_when_essential_expense_is_low() -> None:
    result = buffer(Decimal("1000000"))

    assert result == Decimal("300000")


def test_buffer_uses_percentage_when_essential_expense_is_high() -> None:
    result = buffer(Decimal("5000000"))

    assert result == Decimal("500000")
