"""공용 시뮬레이션 입력을 순수 현금흐름 엔진 입력으로 변환한다."""

from datetime import date

from app.engines.cashflow import (
    DEFAULT_CASHFLOW_POLICY,
    CashflowInput,
    CashflowPolicy,
    CashflowResult,
    calculate_cashflow,
)
from app.schemas.simulation import FinancialSnapshot, SimulationInput


def diagnose_financial_snapshot(
    snapshot: FinancialSnapshot,
    *,
    as_of: date,
    policy: CashflowPolicy = DEFAULT_CASHFLOW_POLICY,
) -> CashflowResult:
    """현재 공개 계약만으로 보수적인 현금흐름 진단을 실행한다.

    공용 ``FinancialSnapshot``에는 아직 월별 이력, 필수/재량 지출 분리,
    예정지출과 가족·의료위험이 없다. 값을 만들어 내지 않고 엔진의 결측·가정
    규약으로 전달한다. ``monthly_expense``는 기존 대출상환액을 제외한 생활비로
    보고 전액을 필수생활비로 해석해 저축 가능액을 과대평가하지 않는다.
    """

    return calculate_cashflow(
        CashflowInput(
            as_of=as_of,
            current_monthly_income=snapshot.monthly_income,
            current_monthly_essential_expense=snapshot.monthly_expense,
            monthly_debt_payment=snapshot.monthly_debt_payment,
            liquid_assets=snapshot.liquid_assets,
            current_emergency_reserve=snapshot.emergency_reserve,
            irregular_essential_expenses=None,
            planned_expenses=None,
            assumptions=(
                "공용 FinancialSnapshot의 monthly_expense 전액을 "
                "필수생활비로 보수적으로 해석했습니다.",
                "monthly_expense는 기존 대출 월 상환액을 제외한 값으로 해석했습니다.",
            ),
        ),
        policy=policy,
    )


def diagnose_cashflow(
    payload: SimulationInput,
    *,
    as_of: date,
    policy: CashflowPolicy = DEFAULT_CASHFLOW_POLICY,
) -> CashflowResult:
    """Diagnose the financial snapshot embedded in a simulation request."""

    return diagnose_financial_snapshot(
        payload.financial_snapshot,
        as_of=as_of,
        policy=policy,
    )


__all__ = ["diagnose_cashflow", "diagnose_financial_snapshot"]
