from datetime import date
from decimal import Decimal

import pytest

from app.engines.loan.existing_debt import (
    UnsupportedRepayMethodError,
    existing_loan_monthly_payment,
)
from app.engines.loan.formulas import pmt

AS_OF = date(2026, 7, 24)
TOLERANCE = Decimal("0.001")


def _within_tolerance(actual: Decimal, expected: Decimal) -> bool:
    return abs(actual - expected) / expected < TOLERANCE


def test_grace_period_mortgage_matches_real_mydata_transfer_amount() -> None:
    # app/data_pipeline/mydata/persona_c_dual_income_mortgage (은행-008/009,
    # bank_009_loan_detail_11020204000005.json) — 거치기간(2024-03~2027-03)
    # 중이라 이자만 상환. 은행-004에 기록된 실제 자동이체액(대출원리금)이
    # 875,000원/월이며 이 값과 정확히 일치한다.
    loan_basic = {
        "issue_date": "20240315",
        "exp_date": "20540315",
        "last_offered_rate": 0.042,
        "repay_method": "05",
        "unredeemed_start": "202403",
        "unredeemed_end": "202703",
    }
    loan_detail = {"balance_amt": 250000000, "loan_principal": 250000000}

    result = existing_loan_monthly_payment(loan_basic, loan_detail, AS_OF)

    assert result == Decimal("875000")


def test_level_payment_credit_loan_matches_real_mydata_transfer_amount() -> None:
    # 같은 페르소나의 신용대출(bank_009_loan_detail_11020204000006.json).
    # 은행-004에 기록된 실제 자동이체액(신용대출원리금)이 1,256,148원/월이며,
    # as_of(2026-07-24)~exp_date(2028-08-10) 잔여 24개월로 계산한 값과
    # 허용오차 0.1% 이내로 일치한다.
    loan_basic = {
        "issue_date": "20250810",
        "exp_date": "20280810",
        "last_offered_rate": 0.058,
        "repay_method": "04",
    }
    loan_detail = {"balance_amt": 28400000, "loan_principal": 40000000}

    result = existing_loan_monthly_payment(loan_basic, loan_detail, AS_OF)

    assert _within_tolerance(result, Decimal("1256148"))


def test_bullet_repayment_is_interest_only() -> None:
    loan_basic = {
        "issue_date": "20250101",
        "exp_date": "20270101",
        "last_offered_rate": 0.05,
        "repay_method": "01",
    }
    loan_detail = {"balance_amt": 100000000, "loan_principal": 100000000}

    result = existing_loan_monthly_payment(loan_basic, loan_detail, AS_OF)

    assert result == Decimal("100000000") * Decimal("0.05") / Decimal(12)


def test_equal_principal_repayment_combines_fixed_principal_and_declining_interest() -> None:
    loan_basic = {
        "issue_date": "20240101",
        "exp_date": "20260101",
        "last_offered_rate": 0.06,
        "repay_method": "02",
    }
    loan_detail = {"balance_amt": 12000000, "loan_principal": 24000000}

    result = existing_loan_monthly_payment(loan_basic, loan_detail, AS_OF)

    # 월 원금 24,000,000/24=1,000,000 + 잔액이자 12,000,000*0.06/12=60,000
    assert result == Decimal("1060000")


def test_grace_period_mortgage_after_grace_ends_uses_level_payment() -> None:
    loan_basic = {
        "issue_date": "20240315",
        "exp_date": "20540315",
        "last_offered_rate": 0.042,
        "repay_method": "05",
        "unredeemed_start": "202403",
        "unredeemed_end": "202703",
    }
    loan_detail = {"balance_amt": 250000000, "loan_principal": 250000000}
    after_grace = date(2027, 4, 1)

    result = existing_loan_monthly_payment(loan_basic, loan_detail, after_grace)

    # _months_between(2027-04-01, 2054-03-15): end.day(15) >= start.day(1)이므로
    # 보정 없이 (2054-2027)*12 + (3-4) = 323개월.
    expected = pmt(Decimal("250000000"), Decimal("0.042"), 323)
    assert result == expected
    assert result != Decimal("250000000") * Decimal("0.042") / Decimal(12)


def test_credit_line_is_unsupported() -> None:
    loan_basic = {
        "issue_date": "20250101",
        "exp_date": "20260101",
        "last_offered_rate": 0.07,
        "repay_method": "08",
    }
    loan_detail = {"balance_amt": 3000000, "loan_principal": 5000000}

    with pytest.raises(UnsupportedRepayMethodError, match="한도거래"):
        existing_loan_monthly_payment(loan_basic, loan_detail, AS_OF)


def test_unrecognized_repay_method_is_unsupported() -> None:
    loan_basic = {
        "issue_date": "20250101",
        "exp_date": "20260101",
        "last_offered_rate": 0.07,
        "repay_method": "12",
    }
    loan_detail = {"balance_amt": 3000000, "loan_principal": 5000000}

    with pytest.raises(UnsupportedRepayMethodError, match="12"):
        existing_loan_monthly_payment(loan_basic, loan_detail, AS_OF)
