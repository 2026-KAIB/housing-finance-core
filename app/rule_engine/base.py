from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RuleDecision:
    rule_code: str
    passed: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    source_version: str | None = None


class Rule[ContextT](Protocol):
    code: str

    def evaluate(self, context: ContextT) -> RuleDecision:
        """컨텍스트를 평가하고 추적 가능한 결정을 반환합니다."""
