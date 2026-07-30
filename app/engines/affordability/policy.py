"""Versioned decision tolerances for property affordability."""

from dataclasses import dataclass
from decimal import Decimal

from app.engines.recommendation.models import DEFAULT_RECOMMENDATION_POLICY


@dataclass(frozen=True)
class AffordabilityPolicy:
    version: str = "property-affordability-policy/1.0.0"
    funding_tolerance: Decimal = DEFAULT_RECOMMENDATION_POLICY.loan_amount_tolerance
    policy_note: str = (
        "자금 부족 허용오차는 대출 추천 엔진과 같은 값을 사용합니다. "
        "스트레스 심사 월 잉여가 현금흐름 Buffer보다 작거나 비상자금 목표가 "
        "충분히 보호되지 않으면 TIGHT로 판정합니다."
    )

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("policy version must not be blank")
        if self.funding_tolerance < 0:
            raise ValueError("funding_tolerance must not be negative")
        if not self.policy_note.strip():
            raise ValueError("policy_note must not be blank")


DEFAULT_AFFORDABILITY_POLICY = AffordabilityPolicy()
