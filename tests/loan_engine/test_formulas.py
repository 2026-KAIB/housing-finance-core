from decimal import Decimal

import pytest

from app.engines.loan.formulas import buffer, dsr, loan_max, pmt

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


def _loan_max_kwargs(**overrides: object) -> dict:
    # 기본값은 모든 조건이 넉넉해서 어떤 한도도 구속하지 않도록 설계했다.
    # 각 테스트는 딱 하나의 조건만 빡빡하게 만들어 그 조건이 실제로 결과를
    # 구속하는지 확인한다 (DESIGN SSOT 부록 A-2).
    defaults: dict = {
        "ltv_limit_amount": Decimal("500000000"),
        "product_limit_amount": Decimal("500000000"),
        "dti_limit_amount": Decimal("500000000"),
        "required_amount": Decimal("500000000"),
        "annual_rate": Decimal("0.035"),
        "months": 360,
        "existing_annual_debt_service": Decimal("0"),
        "annual_income": Decimal("1000000000"),
        "safe_dsr": Decimal("0.4"),
        "post_purchase_monthly_income": Decimal("50000000"),
        "post_purchase_monthly_expense": Decimal("1000000"),
        "other_existing_monthly_debt_service": Decimal("0"),
        "buffer_target": Decimal("300000"),
    }
    defaults.update(overrides)
    return defaults


def test_loan_max_converges_to_the_tightest_amount_limit() -> None:
    result = loan_max(**_loan_max_kwargs(required_amount=Decimal("300000000")))

    assert Decimal("299900000") <= result <= Decimal("300000000")


def test_loan_max_is_bound_by_safe_dsr_when_it_is_the_tightest_condition() -> None:
    kwargs = _loan_max_kwargs(
        existing_annual_debt_service=Decimal("6000000"),
        annual_income=Decimal("60000000"),
        safe_dsr=Decimal("0.30"),
    )

    result = loan_max(**kwargs)

    resulting_dsr = dsr(
        existing_annual_debt_service=kwargs["existing_annual_debt_service"],
        new_annual_debt_service=pmt(result, kwargs["annual_rate"], kwargs["months"]) * 12,
        annual_income=kwargs["annual_income"],
    )
    dsr_just_above = dsr(
        existing_annual_debt_service=kwargs["existing_annual_debt_service"],
        new_annual_debt_service=pmt(
            result + Decimal("5000000"), kwargs["annual_rate"], kwargs["months"]
        )
        * 12,
        annual_income=kwargs["annual_income"],
    )
    assert resulting_dsr <= Decimal("0.30") + Decimal("0.0005")
    assert dsr_just_above > Decimal("0.30")


def test_loan_max_is_bound_by_post_purchase_buffer_when_it_is_the_tightest_condition() -> None:
    kwargs = _loan_max_kwargs(
        post_purchase_monthly_income=Decimal("3000000"),
        post_purchase_monthly_expense=Decimal("1000000"),
        buffer_target=Decimal("300000"),
    )

    result = loan_max(**kwargs)

    surplus = (
        kwargs["post_purchase_monthly_income"]
        - kwargs["post_purchase_monthly_expense"]
        - kwargs["other_existing_monthly_debt_service"]
        - pmt(result, kwargs["annual_rate"], kwargs["months"])
    )
    surplus_just_above = (
        kwargs["post_purchase_monthly_income"]
        - kwargs["post_purchase_monthly_expense"]
        - kwargs["other_existing_monthly_debt_service"]
        - pmt(result + Decimal("5000000"), kwargs["annual_rate"], kwargs["months"])
    )
    assert surplus >= Decimal("300000") - Decimal("500")
    assert surplus_just_above < Decimal("300000")


def test_loan_max_never_exceeds_the_lowest_of_the_amount_limits() -> None:
    result = loan_max(**_loan_max_kwargs(dti_limit_amount=Decimal("50000000")))

    assert result <= Decimal("50000000")


def test_pmt_rejects_zero_months_instead_of_dividing_by_zero() -> None:
    with pytest.raises(ValueError, match="months"):
        pmt(Decimal("100000000"), Decimal("0.035"), 0)


def test_pmt_rejects_negative_months() -> None:
    with pytest.raises(ValueError, match="months"):
        pmt(Decimal("100000000"), Decimal("0.035"), -12)


def test_pmt_rejects_negative_principal() -> None:
    with pytest.raises(ValueError, match="principal"):
        pmt(Decimal("-1"), Decimal("0.035"), 360)


def test_pmt_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="annual_rate"):
        pmt(Decimal("100000000"), Decimal("-0.01"), 360)


def test_dsr_rejects_zero_annual_income_instead_of_dividing_by_zero() -> None:
    with pytest.raises(ValueError, match="annual_income"):
        dsr(
            existing_annual_debt_service=Decimal("0"),
            new_annual_debt_service=Decimal("12000000"),
            annual_income=Decimal("0"),
        )


def test_dsr_rejects_negative_debt_service() -> None:
    with pytest.raises(ValueError, match="new_annual_debt_service"):
        dsr(
            existing_annual_debt_service=Decimal("0"),
            new_annual_debt_service=Decimal("-1"),
            annual_income=Decimal("60000000"),
        )


def test_buffer_rejects_negative_expense() -> None:
    with pytest.raises(ValueError, match="monthly_essential_expense"):
        buffer(Decimal("-1"))


def test_loan_max_rejects_zero_epsilon() -> None:
    with pytest.raises(ValueError, match="epsilon"):
        loan_max(**_loan_max_kwargs(epsilon=Decimal("0")))


def test_loan_max_rejects_negative_epsilon_instead_of_looping_forever() -> None:
    with pytest.raises(ValueError, match="epsilon"):
        loan_max(**_loan_max_kwargs(epsilon=Decimal("-1")))


def test_loan_max_rejects_zero_annual_income() -> None:
    with pytest.raises(ValueError, match="annual_income"):
        loan_max(**_loan_max_kwargs(annual_income=Decimal("0")))


def test_loan_max_rejects_zero_months() -> None:
    with pytest.raises(ValueError, match="months"):
        loan_max(**_loan_max_kwargs(months=0))


def test_loan_max_rejects_negative_amount_limit() -> None:
    with pytest.raises(ValueError, match="dti_limit_amount"):
        loan_max(**_loan_max_kwargs(dti_limit_amount=Decimal("-1")))
