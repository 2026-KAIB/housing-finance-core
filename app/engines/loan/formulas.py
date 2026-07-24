from decimal import Decimal

# 이 모듈은 입력 스키마(어댑터/handoff 연결 방식)와 무관하게 확정된 순수 계산
# 공식만 담는다 (DESIGN SSOT §13.3 PMT, §13.2/A-12 DSR, 부록 A-8 Buffer).
# 상품·정책 데이터를 어떻게 받아올지는 아직 팀 논의 중이므로, 이 함수들은
# Decimal 입력만 받고 그 상위 조립(Adapter/계산 엔진 본체)에는 관여하지 않는다.


def monthly_rate(annual_rate: Decimal) -> Decimal:
    """대출 월금리는 명목환산(연이율/12)을 쓴다 (§13.3 규약, 예적금 실효환산과 다름)."""
    return annual_rate / Decimal(12)


def pmt(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """원리금균등 월 상환액 (DESIGN SSOT §13.3).

    PMT = L × i(1+i)^n / ((1+i)^n − 1), i = 연이율 ÷ 12
    """
    i = monthly_rate(annual_rate)
    if i == 0:
        return principal / Decimal(months)
    growth = (1 + i) ** months
    return principal * i * growth / (growth - 1)


def dsr(
    *,
    existing_annual_debt_service: Decimal,
    new_annual_debt_service: Decimal,
    annual_income: Decimal,
) -> Decimal:
    """DSR = (기존 + 신규) 연간 원리금 상환액 ÷ 연간 소득 (§13.2, 부록 A-12).

    "모든 금융부채"는 기존 대출과 신규(시뮬레이션 대상) 대출을 모두 포함한다.
    """
    return (existing_annual_debt_service + new_annual_debt_service) / annual_income


def buffer(monthly_essential_expense: Decimal) -> Decimal:
    """최소 여유자금(Buffer) = max(300,000원, 필수생활비 × 0.10) (부록 A-8)."""
    return max(Decimal("300000"), monthly_essential_expense * Decimal("0.10"))


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
    epsilon: Decimal = Decimal("100000"),
) -> Decimal:
    """대출 가능액 이분 탐색 (DESIGN SSOT 부록 A-2).

    정책 상한(LTV·상품·DTI 한도)은 이미 금액으로 환산된 값을 인자로 받는다 —
    비율→금액 변환은 이 함수의 책임이 아니다. hi 초기값은 그 한도들과 실제
    필요액 중 최솟값이며, DSR·구매후 현금흐름(Buffer) 조건을 동시에 만족하는
    최대 대출액을 찾을 때까지 이분 탐색한다. L 증가 → pmt·dsr 증가, 월 잉여
    감소로 feasible은 L에 대해 단조이므로 이분 탐색이 유효하다(A-2 원문).
    """
    lo = Decimal("0")
    hi = min(ltv_limit_amount, product_limit_amount, dti_limit_amount, required_amount)

    while (hi - lo) > epsilon:
        candidate = (lo + hi) / 2
        new_pmt = pmt(candidate, annual_rate, months)
        candidate_dsr = dsr(
            existing_annual_debt_service=existing_annual_debt_service,
            new_annual_debt_service=new_pmt * 12,
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
