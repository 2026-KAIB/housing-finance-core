from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_id: str
    score: Decimal
    eligible: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


class Engine[InputT, OutputT](Protocol):
    def calculate(self, payload: InputT) -> OutputT:
        """검증된 입력으로 결과를 계산합니다."""
