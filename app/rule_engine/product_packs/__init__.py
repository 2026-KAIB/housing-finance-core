from app.rule_engine.product_packs.engine import evaluate_product
from app.rule_engine.product_packs.handoff import (
    ProductCandidate,
    ProductEngineHandoff,
    ProductRoutingResult,
    route_product_candidates,
)
from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductCategory,
    ProductEvaluationRequest,
    ProductEvaluationResult,
    ProductRuleDecision,
    ProductRulePack,
)
from app.rule_engine.product_packs.registry import (
    DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
    ProductRulePackAmbiguousError,
    ProductRulePackNotFoundError,
    ProductRulePackRegistry,
    normalize_product_name,
)
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 외부 모듈은 하위 파일에 직접 의존하지 말고 여기서 공개한 이름만 import한다.
# 새 상품 추가 작업은 `packs/`에 파일을 만들고 `packs/__init__.py`에 등록하면 끝난다.
# 기본 레지스트리는 등록된 Pack을 상품명과 기준일로 찾아 evaluate_product에 제공한다.

__all__ = [
    "DEFAULT_PRODUCT_RULE_PACK_REGISTRY",
    "ComparisonOperator",
    "ComparisonRule",
    "EvaluationStatus",
    "PredicateRule",
    "ProductCategory",
    "ProductCandidate",
    "ProductEngineHandoff",
    "ProductEvaluationRequest",
    "ProductEvaluationResult",
    "ProductRoutingResult",
    "ProductRuleDecision",
    "ProductRulePack",
    "ProductRulePackAmbiguousError",
    "ProductRulePackNotFoundError",
    "ProductRulePackRegistry",
    "evaluate_product",
    "normalize_product_name",
    "route_product_candidates",
]
