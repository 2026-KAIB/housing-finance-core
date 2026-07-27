from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Literal

from app.engines.loan.formulas import pmt

# DSR 산정용 만기일시상환("01") 대출 목적. 마이데이터 은행-008/009 원본에는
# "대출 목적" 필드가 없으므로 호출자가 명시적으로 넘겨야 한다(추측 금지).
LoanCategory = Literal["jeonse", "credit", "mortgage"]

# 신용대출 일시상환의 DSR 산정만기 = 5년(60개월) 분할상환 환산.
# 출처: 금융위원회 "금융회사 여신심사 선진화 방안"(2017.11.26) + 금융감독원
# "은행업감독업무시행세칙 등 5개 시행세칙 개정예고"(2023.4.7) — 부동산위키
# 정리표(2026-07-27 확인)로 교차검증. 2017년 최초 발표 시에는 10년이었으나
# 이후 개정으로 5년으로 단축되었다(정확한 개정 시행일은 미확인이나, 현재
# 통용되는 값은 5년).
_CREDIT_LOAN_DSR_CONVERSION_MONTHS = 60

# 주담대 원금일시상환의 DSR 산정만기 상한 = 10년(120개월). 실제 대출기간이
# 이보다 짧으면 실제 대출기간을 쓰고, 길면 120개월로 상한을 건다("최대 10년").
# 출처: 위와 동일(부동산위키 "총부채원리금상환비율" 정리표, 2026-07-27 확인).
_MORTGAGE_BULLET_DSR_MAX_CONVERSION_MONTHS = 120

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


def _linear_principal_plus_balance_interest(
    loan_principal: Decimal,
    balance_amt: Decimal,
    annual_rate: Decimal,
    conversion_months: int,
) -> Decimal:
    """원금은 대출총액을 산정만기로 선형 분할, 이자는 현재 잔액 기준 실제 부담액.

    금융위 2017.11.26 발표 예시로 검증한 형태(원리금균등/PMT가 아님):
    연봉 5천만, 연 4.0%, 대출총액 5천만, 산정만기 10년(당시) → 이자
    200만원(5천만×4%) + 원금 500만원(5천만/10년) = 연 700만원.
    """
    monthly_principal = loan_principal / Decimal(conversion_months)
    monthly_interest = balance_amt * annual_rate / Decimal(12)
    return monthly_principal + monthly_interest


def existing_loan_dsr_monthly_payment(
    loan_basic: Mapping[str, object],
    loan_detail: Mapping[str, object],
    as_of: date,
    loan_category: LoanCategory,
) -> Decimal:
    """DSR 분자(§13.2/부록 A-12)에 반영할 기존 대출의 월 상환액.

    `existing_loan_monthly_payment`(실제 현금흐름)와 값이 갈리는 지점은
    상환방식이 "01"(만기일시상환)일 때뿐이다 — DSR은 실제 이자만 내는 대출도
    분할상환 가정으로 환산해 반영하는데, 그 환산 방식이 대출 목적별로 다르다:

    - "jeonse"(전세자금대출): 실제 이자상환액만 반영(원금 미반영) — 실제
      현금흐름과 동일한 값.
    - "credit"(신용대출): 원금은 5년(60개월) 선형 분할
      (`_CREDIT_LOAN_DSR_CONVERSION_MONTHS`) + 이자는 잔액 기준 실제 부담액.
    - "mortgage"(주택담보대출): 원금은 `min(실제 대출기간, 10년)`으로 선형 분할
      (`_MORTGAGE_BULLET_DSR_MAX_CONVERSION_MONTHS`) + 이자는 잔액 기준 실제
      부담액.

    출처: 금융위원회 "금융회사 여신심사 선진화 방안"(2017.11.26) + 금융감독원
    "은행업감독업무시행세칙 등 5개 시행세칙 개정예고"(2023.4.7) — 부동산위키
    정리표로 교차검증(2026-07-27 확인).

    "02"/"04"/"05"(분할상환)는 실제 상환액이 곧 DSR 반영액이므로
    `existing_loan_monthly_payment`와 동일한 값을 그대로 반환한다.
    "08"(한도거래/마이너스통장)은 산정 기준이 "한도 전액"이라는 출처와 "실제
    사용액"이라는 출처가 계속 상충해 `UnsupportedRepayMethodError`를
    발생시킨다.
    """
    repay_method = str(loan_basic["repay_method"])

    if repay_method == "01":
        loan_principal = Decimal(str(loan_detail["loan_principal"]))
        balance_amt = Decimal(str(loan_detail["balance_amt"]))
        annual_rate = Decimal(str(loan_basic["last_offered_rate"]))

        if loan_category == "jeonse":
            return balance_amt * annual_rate / Decimal(12)

        if loan_category == "credit":
            return _linear_principal_plus_balance_interest(
                loan_principal, balance_amt, annual_rate, _CREDIT_LOAN_DSR_CONVERSION_MONTHS
            )

        issue_date = _parse_date(str(loan_basic["issue_date"]))
        exp_date = _parse_date(str(loan_basic["exp_date"]))
        total_months = _months_between(issue_date, exp_date)
        conversion_months = min(total_months, _MORTGAGE_BULLET_DSR_MAX_CONVERSION_MONTHS)
        return _linear_principal_plus_balance_interest(
            loan_principal, balance_amt, annual_rate, conversion_months
        )

    return existing_loan_monthly_payment(loan_basic, loan_detail, as_of)
