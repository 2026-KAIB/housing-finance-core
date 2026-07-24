from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductEvaluationResult,
)
from app.rule_engine.product_packs.registry import (
    DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
    ProductRulePackRegistry,
)

# 이 함수가 상품별 Rule Pack의 단일 실행 진입점이다.
# API나 추천 서비스는 상품마다 별도 함수를 호출하지 말고 이 함수만 호출한다.
# FAIL이 하나라도 있으면 FAIL, FAIL 없이 UNKNOWN이 있으면 UNKNOWN, 모두 통과하면 PASS다.
# 상품 후보 여러 개를 평가할 때는 상위 서비스가 상품명 목록을 순회해 결과를 모은다.


def evaluate_product(
    request: ProductEvaluationRequest,
    registry: ProductRulePackRegistry = DEFAULT_PRODUCT_RULE_PACK_REGISTRY,
) -> ProductEvaluationResult:
    pack = registry.resolve(request.product_name, request.as_of)
    decisions = tuple(
        rule.evaluate(request, source_version=pack.source_version)
        for rule in pack.rules
    )

    if any(decision.status is EvaluationStatus.FAIL for decision in decisions):
        status = EvaluationStatus.FAIL
    elif any(decision.status is EvaluationStatus.UNKNOWN for decision in decisions):
        status = EvaluationStatus.UNKNOWN
    else:
        status = EvaluationStatus.PASS

    return ProductEvaluationResult(
        requested_product_name=request.product_name,
        product_name=pack.product_name,
        category=pack.category,
        status=status,
        as_of=request.as_of,
        pack_version=pack.version,
        decisions=decisions,
    )
