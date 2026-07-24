from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.rule_engine.product_packs.models import (
    EvaluationStatus,
    ProductEvaluationRequest,
    ProductRuleDecision,
)

# 상품 Pack에서는 먼저 ComparisonRule로 단순 비교를 표현한다.
# 여러 필드, 예외, AND/OR 등 상품 고유 조건은 PredicateRule 함수로 작성한다.
# PredicateRule은 True=PASS, False=FAIL, None=UNKNOWN을 반환해야 한다.
# 원문을 억지로 추정하지 말고 해석이 불확실하면 반드시 None을 반환한다.


class ComparisonOperator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    IN = "IN"
    NOT_IN = "NOT_IN"
    BETWEEN = "BETWEEN"


@dataclass(frozen=True)
class ComparisonRule:
    code: str
    field_name: str
    operator: ComparisonOperator
    expected: object
    failure_reason: str
    unknown_reason: str | None = None

    def evaluate(
        self,
        request: ProductEvaluationRequest,
        *,
        source_version: str,
    ) -> ProductRuleDecision:
        actual = request.facts.get(self.field_name)
        if actual is None:
            reason = self.unknown_reason or f"'{self.field_name}' 값이 없어 판정할 수 없습니다."
            return _decision(self.code, EvaluationStatus.UNKNOWN, reason, source_version)

        try:
            passed = _compare(actual, self.operator, self.expected)
        except (TypeError, ValueError):
            reason = self.unknown_reason or (
                f"'{self.field_name}' 값의 형식이 규칙과 맞지 않아 판정할 수 없습니다."
            )
            return _decision(self.code, EvaluationStatus.UNKNOWN, reason, source_version)

        if passed:
            return _decision(self.code, EvaluationStatus.PASS, None, source_version)
        return _decision(
            self.code,
            EvaluationStatus.FAIL,
            self.failure_reason,
            source_version,
        )


Predicate = Callable[[Mapping[str, object]], bool | None]


@dataclass(frozen=True)
class PredicateRule:
    code: str
    predicate: Predicate
    failure_reason: str
    required_fields: tuple[str, ...] = field(default_factory=tuple)
    unknown_reason: str | None = None

    def evaluate(
        self,
        request: ProductEvaluationRequest,
        *,
        source_version: str,
    ) -> ProductRuleDecision:
        missing_fields = tuple(
            name for name in self.required_fields if request.facts.get(name) is None
        )
        if missing_fields:
            reason = self.unknown_reason or (
                f"필수 입력값({', '.join(missing_fields)})이 없어 판정할 수 없습니다."
            )
            return _decision(self.code, EvaluationStatus.UNKNOWN, reason, source_version)

        try:
            passed = self.predicate(request.facts)
        except (ArithmeticError, KeyError, TypeError, ValueError):
            reason = self.unknown_reason or "입력값 형식이 규칙과 맞지 않아 판정할 수 없습니다."
            return _decision(self.code, EvaluationStatus.UNKNOWN, reason, source_version)

        if passed is None:
            reason = self.unknown_reason or "조건을 확정할 정보가 부족해 판정할 수 없습니다."
            return _decision(self.code, EvaluationStatus.UNKNOWN, reason, source_version)
        if passed:
            return _decision(self.code, EvaluationStatus.PASS, None, source_version)
        return _decision(
            self.code,
            EvaluationStatus.FAIL,
            self.failure_reason,
            source_version,
        )


def _compare(actual: object, operator: ComparisonOperator, expected: object) -> bool:
    if operator is ComparisonOperator.EQ:
        return actual == expected
    if operator is ComparisonOperator.NE:
        return actual != expected
    if operator is ComparisonOperator.GT:
        return actual > expected  # type: ignore[operator]
    if operator is ComparisonOperator.GTE:
        return actual >= expected  # type: ignore[operator]
    if operator is ComparisonOperator.LT:
        return actual < expected  # type: ignore[operator]
    if operator is ComparisonOperator.LTE:
        return actual <= expected  # type: ignore[operator]
    if operator in (ComparisonOperator.IN, ComparisonOperator.NOT_IN):
        if isinstance(expected, (str, bytes)) or not isinstance(expected, Sequence):
            raise TypeError("IN/NOT_IN의 expected는 문자열이 아닌 Sequence여야 합니다.")
        contained = actual in expected
        return contained if operator is ComparisonOperator.IN else not contained
    if operator is ComparisonOperator.BETWEEN:
        if (
            isinstance(expected, (str, bytes))
            or not isinstance(expected, Sequence)
            or len(expected) != 2
        ):
            raise ValueError("BETWEEN의 expected는 최솟값과 최댓값 두 개여야 합니다.")
        lower, upper = expected
        return lower <= actual <= upper  # type: ignore[operator]
    raise ValueError(f"지원하지 않는 비교 연산자입니다: {operator}")


def _decision(
    rule_code: str,
    status: EvaluationStatus,
    reason: str | None,
    source_version: str,
) -> ProductRuleDecision:
    reasons = () if reason is None else (reason,)
    return ProductRuleDecision(
        rule_code=rule_code,
        status=status,
        reasons=reasons,
        source_version=source_version,
    )
