"""여러 금융 엔진이 공유하는 생활안전 공식을 정의한다."""

from decimal import Decimal


def cashflow_buffer(
    monthly_essential_expense: Decimal,
    *,
    floor: Decimal = Decimal("300000"),
    ratio: Decimal = Decimal("0.10"),
) -> Decimal:
    """최소 월 현금흐름 여유자금.

    ``max(30만원, 필수생활비 × 10%)``가 기본 정책이다. 비상자금 목표액과는
    다른 개념이며, 대출 실행 또는 저축 배분 후에도 매달 남겨 둘 현금흐름이다.
    """

    if monthly_essential_expense < 0:
        raise ValueError("monthly_essential_expense은(는) 음수일 수 없습니다.")
    if floor < 0:
        raise ValueError("floor은(는) 음수일 수 없습니다.")
    if ratio < 0:
        raise ValueError("ratio은(는) 음수일 수 없습니다.")
    return max(floor, monthly_essential_expense * ratio)
