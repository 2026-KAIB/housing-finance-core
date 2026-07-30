from decimal import Decimal

from app.engines.safety import cashflow_buffer

# 이 모듈은 입력 스키마(어댑터/handoff 연결 방식)와 무관하게 확정된 순수 계산
# 공식만 담는다 (DESIGN SSOT §13.3 PMT, §13.2/A-12 DSR, 부록 A-8 Buffer).
# 상품·정책 데이터를 어떻게 받아올지는 아직 팀 논의 중이므로, 이 함수들은
# Decimal 입력만 받고 그 상위 조립(Adapter/계산 엔진 본체)에는 관여하지 않는다.
#
# 단위 계약: annual_rate는 비율(3.5% → Decimal("0.035")), 금액은 원, months는
# 개월이다. 이 계약을 어기는 값(0을 초과하지 않는 기간, 음수 금액 등)은 계산
# 불가능한 입력이므로 ValueError로 즉시 실패한다 — 결측/UNKNOWN 판정으로
# 바꿀지는 이 함수를 호출하는 Adapter/서비스 계층의 책임이다.


def _require_positive(value: Decimal | int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name}은(는) 0보다 커야 합니다.")


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def monthly_rate(annual_rate: Decimal) -> Decimal:
    """대출 월금리는 명목환산(연이율/12)을 쓴다 (§13.3 규약, 예적금 실효환산과 다름)."""
    return annual_rate / Decimal(12)


def pmt(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """원리금균등 월 상환액 (DESIGN SSOT §13.3).

    PMT = L × i(1+i)^n / ((1+i)^n − 1), i = 연이율 ÷ 12
    """
    _require_non_negative(principal, "principal")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(months, "months")

    i = monthly_rate(annual_rate)
    if i == 0:
        return principal / Decimal(months)
    growth = (1 + i) ** months
    return principal * i * growth / (growth - 1)


def principal_from_pmt(monthly_payment: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """월 상환액 상한에서 역산한 원금 = pmt()의 역함수 (§13.3).

    L = PMT × ((1+i)^n − 1) / (i(1+i)^n), i = 연이율 ÷ 12

    DTI·DSR 한도는 "연간 상환액이 소득의 x% 이내"라는 **상환액 제약**이므로,
    이를 금액 한도로 바꾸려면 상환액에서 원금을 되돌려야 한다(§9.1).
    """
    _require_non_negative(monthly_payment, "monthly_payment")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(months, "months")

    i = monthly_rate(annual_rate)
    if i == 0:
        return monthly_payment * Decimal(months)
    growth = (1 + i) ** months
    return monthly_payment * (growth - 1) / (i * growth)


def dsr(
    *,
    existing_annual_debt_service: Decimal,
    new_annual_debt_service: Decimal,
    annual_income: Decimal,
) -> Decimal:
    """DSR = (기존 + 신규) 연간 원리금 상환액 ÷ 연간 소득 (§13.2, 부록 A-12).

    "모든 금융부채"는 기존 대출과 신규(시뮬레이션 대상) 대출을 모두 포함한다.
    """
    _require_non_negative(existing_annual_debt_service, "existing_annual_debt_service")
    _require_non_negative(new_annual_debt_service, "new_annual_debt_service")
    _require_positive(annual_income, "annual_income")

    return (existing_annual_debt_service + new_annual_debt_service) / annual_income


def buffer(monthly_essential_expense: Decimal) -> Decimal:
    """최소 여유자금(Buffer) = max(300,000원, 필수생활비 × 0.10) (부록 A-8)."""
    return cashflow_buffer(monthly_essential_expense)


def loan_max(
    *,
    ltv_limit_amount: Decimal,
    product_limit_amount: Decimal,
    dti_limit_amount: Decimal,
    required_amount: Decimal,
    annual_rate: Decimal,
    months: int,
    existing_annual_debt_service: Decimal,
    annual_income: Decimal,
    safe_dsr: Decimal,
    post_purchase_monthly_income: Decimal,
    post_purchase_monthly_expense: Decimal,
    other_existing_monthly_debt_service: Decimal,
    buffer_target: Decimal,
    dsr_annual_rate: Decimal | None = None,
    epsilon: Decimal = Decimal("100000"),
) -> Decimal:
    """대출 가능액 이분 탐색 (DESIGN SSOT 부록 A-2).

    정책 상한(LTV·상품·DTI 한도)은 이미 금액으로 환산된 값을 인자로 받는다 —
    비율→금액 변환은 이 함수의 책임이 아니다. hi 초기값은 그 한도들과 실제
    필요액 중 최솟값이며, DSR·구매후 현금흐름(Buffer) 조건을 동시에 만족하는
    최대 대출액을 찾을 때까지 이분 탐색한다. L 증가 → pmt·dsr 증가, 월 잉여
    감소로 feasible은 L에 대해 단조이므로 이분 탐색이 유효하다(A-2 원문).

    **금리는 두 곳에 쓰이며 서로 다를 수 있다.** `dsr_annual_rate`를 주면 DSR
    판정에만 그 금리를 쓰고, 월 현금흐름(Buffer) 판정에는 언제나 실제 금리인
    `annual_rate`를 쓴다. 스트레스 DSR이 정확히 이 구조다 — 심사는 가산금리를
    올린 기준으로 하되 차주가 실제로 내는 돈은 실제 금리 기준이기 때문이다
    (`app/regulations/stress_dsr.py`). 주지 않으면 두 판정 모두 실제 금리를 쓰며,
    이는 스트레스 금리를 적용하지 않는다는 뜻이므로 **한도가 과대평가된다.**

    반환값은 항상 실제 가능한 최대 대출액 이하이며(보수적 하향값), 오차는
    epsilon 미만이다 — epsilon 단위로 절사하는 정책은 호출하는 쪽이 정한다.
    """
    _require_positive(epsilon, "epsilon")
    _require_positive(months, "months")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(annual_income, "annual_income")

    assessment_rate = annual_rate if dsr_annual_rate is None else dsr_annual_rate
    _require_non_negative(assessment_rate, "dsr_annual_rate")
    if assessment_rate < annual_rate:
        raise ValueError(
            "dsr_annual_rate는 실제 금리보다 낮을 수 없습니다 "
            f"(annual_rate={annual_rate}, dsr_annual_rate={assessment_rate})."
        )
    for name, value in (
        ("ltv_limit_amount", ltv_limit_amount),
        ("product_limit_amount", product_limit_amount),
        ("dti_limit_amount", dti_limit_amount),
        ("required_amount", required_amount),
        ("existing_annual_debt_service", existing_annual_debt_service),
        ("safe_dsr", safe_dsr),
        ("post_purchase_monthly_income", post_purchase_monthly_income),
        ("post_purchase_monthly_expense", post_purchase_monthly_expense),
        ("other_existing_monthly_debt_service", other_existing_monthly_debt_service),
        ("buffer_target", buffer_target),
    ):
        _require_non_negative(value, name)

    lo = Decimal("0")
    hi = min(ltv_limit_amount, product_limit_amount, dti_limit_amount, required_amount)

    while (hi - lo) > epsilon:
        candidate = (lo + hi) / 2
        # 실제 상환액(현금흐름 판정용)과 심사용 상환액(DSR 판정용)을 나눈다.
        new_pmt = pmt(candidate, annual_rate, months)
        assessed_pmt = (
            new_pmt if assessment_rate == annual_rate else pmt(candidate, assessment_rate, months)
        )
        candidate_dsr = dsr(
            existing_annual_debt_service=existing_annual_debt_service,
            new_annual_debt_service=assessed_pmt * 12,
            annual_income=annual_income,
        )
        monthly_surplus = (
            post_purchase_monthly_income
            - post_purchase_monthly_expense
            - other_existing_monthly_debt_service
            - new_pmt
        )
        feasible = candidate_dsr <= safe_dsr and monthly_surplus >= buffer_target
        if feasible:
            lo = candidate
        else:
            hi = candidate

    return lo
