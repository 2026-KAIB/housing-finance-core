from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from app.engines.loan.formulas import pmt

# 마이데이터 은행-008(대출 기본)·은행-009(대출 상세) 원본에서 "기존 대출의 월
# 상환액"을 계산한다. DSR 분자(§13.2/부록 A-12)는 기존+신규 대출을 모두 포함
# 하므로, 이 값 × 12가 loan_max()/dsr()의 existing_annual_debt_service가 된다.
# 상환방식(repay_method, [첨부4] 코드)마다 계산식이 달라 여기서 분기한다.
# 참고: app/data_pipeline/mydata/mydata_design.md §8.
#
# repay_method="04"(원리금균등)의 잔여 개월 계산은 실제 mydata 페르소나 C의
# 신용대출(발급 40,000,000원, 연 5.8%, balance_amt=28,400,000, exp_date
# 2028-08-10)로 검증했다 — as_of=2026-07-24 기준 잔여 24개월로 계산한 월
# 상환액이 은행-004에 기록된 실제 자동이체액 1,256,148원과 일치한다.


class UnsupportedRepayMethodError(ValueError):
    """DSR 산정 공식이 아직 합의되지 않았거나 지원하지 않는 상환방식."""


def _parse_date(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def _parse_year_month(value: str) -> tuple[int, int]:
    return int(value[:4]), int(value[4:6])


def _months_between(start: date, end: date) -> int:
    """start에서 end까지의 완전한 개월 수(내림)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _is_in_grace_period(loan_basic: Mapping[str, object], as_of: date) -> bool:
    start = loan_basic.get("unredeemed_start")
    end = loan_basic.get("unredeemed_end")
    if start is None or end is None:
        return False
    as_of_ym = (as_of.year, as_of.month)
    return _parse_year_month(str(start)) <= as_of_ym <= _parse_year_month(str(end))


def existing_loan_monthly_payment(
    loan_basic: Mapping[str, object],
    loan_detail: Mapping[str, object],
    as_of: date,
) -> Decimal:
    """은행-008/009 원본으로 기존 대출의 현재 월 상환액을 계산한다.

    지원 방식(마이데이터 [첨부4] MVP 필수 5종 중 4종):
    - "01" 만기일시상환: 이자만 (balance_amt × 월금리)
    - "02" 원금균등분할상환: 원금균등분(원금/총개월) + 잔액 이자
    - "04" 원리금균등분할상환: PMT(balance_amt, 연이율, 잔여개월)
    - "05" 거치식-원리금균등: 거치기간 중이면 이자만, 종료 후 "04"와 동일
    - "08" 한도거래(마이너스통장)는 DSR 산정 기준(한도 vs 사용액)이 아직
      팀 합의 전이라 `UnsupportedRepayMethodError`를 발생시킨다.
    """
    repay_method = str(loan_basic["repay_method"])
    balance_amt = Decimal(str(loan_detail["balance_amt"]))
    annual_rate = Decimal(str(loan_basic["last_offered_rate"]))
    exp_date = _parse_date(str(loan_basic["exp_date"]))

    if repay_method == "01":
        return balance_amt * annual_rate / Decimal(12)

    if repay_method == "02":
        issue_date = _parse_date(str(loan_basic["issue_date"]))
        loan_principal = Decimal(str(loan_detail["loan_principal"]))
        total_months = _months_between(issue_date, exp_date)
        monthly_principal = loan_principal / Decimal(total_months)
        monthly_interest = balance_amt * annual_rate / Decimal(12)
        return monthly_principal + monthly_interest

    if repay_method == "04":
        remaining_months = _months_between(as_of, exp_date)
        return pmt(balance_amt, annual_rate, remaining_months)

    if repay_method == "05":
        if _is_in_grace_period(loan_basic, as_of):
            return balance_amt * annual_rate / Decimal(12)
        remaining_months = _months_between(as_of, exp_date)
        return pmt(balance_amt, annual_rate, remaining_months)

    if repay_method == "08":
        raise UnsupportedRepayMethodError(
            "한도거래(마이너스통장)는 DSR 산정 기준(한도 vs 사용액)이 아직 "
            "팀 합의 전이라 계산할 수 없습니다."
        )

    raise UnsupportedRepayMethodError(
        f"지원하지 않는 상환방식입니다: {repay_method!r} (mydata_design.md §8.2 MVP 범위 밖)"
    )
