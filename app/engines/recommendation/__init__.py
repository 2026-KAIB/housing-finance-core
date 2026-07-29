"""대출과 예·적금 결과를 결측 상태까지 보존해 종합하는 순수 추천 엔진."""

from app.engines.recommendation.engine import (
    build_combined_recommendation,
    recommend_loans,
    recommend_savings,
)
from app.engines.recommendation.models import (
    DEFAULT_RECOMMENDATION_POLICY,
    CombinedRecommendationInput,
    CombinedRecommendationResult,
    ComponentStatus,
    DecisionStatus,
    LoanCandidateInput,
    LoanOptionRecommendation,
    LoanRecommendationInput,
    RecommendationPolicy,
    RecommendationStatus,
    SavingsAllocationInput,
    SavingsPlanInput,
    SavingsPlanStatus,
    ScoreStatus,
)

__all__ = [
    "DEFAULT_RECOMMENDATION_POLICY",
    "CombinedRecommendationInput",
    "CombinedRecommendationResult",
    "ComponentStatus",
    "DecisionStatus",
    "LoanCandidateInput",
    "LoanOptionRecommendation",
    "LoanRecommendationInput",
    "RecommendationPolicy",
    "RecommendationStatus",
    "SavingsAllocationInput",
    "SavingsPlanInput",
    "SavingsPlanStatus",
    "ScoreStatus",
    "build_combined_recommendation",
    "recommend_loans",
    "recommend_savings",
]
