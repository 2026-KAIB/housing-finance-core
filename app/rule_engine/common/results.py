from dataclasses import dataclass

from app.rule_engine.base import RuleDecision


@dataclass(frozen=True)
class RuleSetResult:
    """여러 RuleDecision을 하나의 통과/탈락 판정으로 묶는다.

    하나라도 미충족 시 전체 탈락(DESIGN SSOT §13.1 / §11.1: 필수조건은
    점수와 무관하게 우선 판정).
    """

    eligible: bool
    decisions: tuple[RuleDecision, ...]

    @property
    def failed_decisions(self) -> tuple[RuleDecision, ...]:
        return tuple(decision for decision in self.decisions if not decision.passed)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(reason for decision in self.failed_decisions for reason in decision.reasons)
