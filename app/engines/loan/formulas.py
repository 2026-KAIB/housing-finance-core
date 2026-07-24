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
