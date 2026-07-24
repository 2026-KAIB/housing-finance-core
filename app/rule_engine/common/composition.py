from collections.abc import Sequence

from app.rule_engine.base import Rule
from app.rule_engine.common.results import RuleSetResult


def evaluate_all[ContextT](rules: Sequence[Rule[ContextT]], context: ContextT) -> RuleSetResult:
    """모든 규칙을 평가하고 결과를 취합한다.

    규칙 하나라도 실패하면 전체 `eligible=False` (DESIGN SSOT §13.1 필수조건 원칙).
    개별 사유·규칙 코드·데이터 버전은 각 RuleDecision에 보존된다.
    """
    decisions = tuple(rule.evaluate(context) for rule in rules)
    eligible = all(decision.passed for decision in decisions)
    return RuleSetResult(eligible=eligible, decisions=decisions)
