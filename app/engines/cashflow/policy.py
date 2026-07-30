"""현금흐름·비상자금 엔진의 버전형 내부 정책."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CashflowPolicy:
    """공식과 조정 가능한 내부 가중치를 한곳에서 관리한다.

    위험지수 가중치와 비상자금 3~9개월 공식은 공식 설계안 §6을 따른다.
    CV 정규화 상한과 결측 중립값은 공식 기준이 아닌 MVP 내부 정책이므로
    버전과 함께 결과에 노출한다.
    """

    version: str = "cashflow-policy@1.0.0"
    source: str = "주택구매 금융컨설팅 공식 설계안 §5~§7"

    safe_income_percentile: Decimal = Decimal("0.25")
    safe_expense_percentile: Decimal = Decimal("0.75")
    minimum_history_months_for_percentile: int = 6
    minimum_history_months_for_average: int = 3

    income_volatility_weight: Decimal = Decimal("0.35")
    expense_volatility_weight: Decimal = Decimal("0.25")
    debt_burden_weight: Decimal = Decimal("0.25")
    family_medical_weight: Decimal = Decimal("0.15")

    income_cv_full_risk: Decimal = Decimal("0.50")
    expense_cv_full_risk: Decimal = Decimal("0.30")
    debt_burden_full_risk_ratio: Decimal = Decimal("0.40")
    missing_risk_component: Decimal = Decimal("0.50")

    emergency_base_months: Decimal = Decimal("3")
    emergency_extra_months: Decimal = Decimal("6")
    default_emergency_build_months: int = 12

    buffer_floor: Decimal = Decimal("300000")
    buffer_ratio: Decimal = Decimal("0.10")

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.source.strip():
            raise ValueError("정책 버전과 출처는 비어 있을 수 없습니다.")
        for name, value in (
            ("safe_income_percentile", self.safe_income_percentile),
            ("safe_expense_percentile", self.safe_expense_percentile),
            ("missing_risk_component", self.missing_risk_component),
        ):
            if not Decimal(0) <= value <= Decimal(1):
                raise ValueError(f"{name}은(는) 0 이상 1 이하여야 합니다.")
        for name, value in (
            ("minimum_history_months_for_percentile", self.minimum_history_months_for_percentile),
            ("minimum_history_months_for_average", self.minimum_history_months_for_average),
            ("default_emergency_build_months", self.default_emergency_build_months),
        ):
            if value <= 0:
                raise ValueError(f"{name}은(는) 0보다 커야 합니다.")
        if self.minimum_history_months_for_average > self.minimum_history_months_for_percentile:
            raise ValueError("평균 사용 최소 개월은 분위값 사용 최소 개월보다 클 수 없습니다.")
        for name, value in (
            ("income_cv_full_risk", self.income_cv_full_risk),
            ("expense_cv_full_risk", self.expense_cv_full_risk),
            ("debt_burden_full_risk_ratio", self.debt_burden_full_risk_ratio),
            ("emergency_base_months", self.emergency_base_months),
            ("emergency_extra_months", self.emergency_extra_months),
        ):
            if value <= 0:
                raise ValueError(f"{name}은(는) 0보다 커야 합니다.")
        for name, value in (
            ("buffer_floor", self.buffer_floor),
            ("buffer_ratio", self.buffer_ratio),
        ):
            if value < 0:
                raise ValueError(f"{name}은(는) 음수일 수 없습니다.")

        weights = (
            self.income_volatility_weight,
            self.expense_volatility_weight,
            self.debt_burden_weight,
            self.family_medical_weight,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("위험지수 가중치는 음수일 수 없습니다.")
        if sum(weights, Decimal(0)) != Decimal(1):
            raise ValueError("위험지수 가중치 합은 1이어야 합니다.")


DEFAULT_CASHFLOW_POLICY = CashflowPolicy()
