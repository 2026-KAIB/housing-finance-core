"""Public contracts and calculator for property-level purchase affordability."""

from app.engines.affordability.engine import evaluate_property_affordability
from app.engines.affordability.models import (
    AffordabilityVerdict,
    PropertyAffordabilityInput,
    PropertyAffordabilityResult,
)
from app.engines.affordability.policy import (
    DEFAULT_AFFORDABILITY_POLICY,
    AffordabilityPolicy,
)

__all__ = [
    "DEFAULT_AFFORDABILITY_POLICY",
    "AffordabilityPolicy",
    "AffordabilityVerdict",
    "PropertyAffordabilityInput",
    "PropertyAffordabilityResult",
    "evaluate_property_affordability",
]
