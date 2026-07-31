"""작성·검증 파이프라인이 보고서 **종류**에 의존하지 않게 하는 계약.

목적:
    지금까지 작성 에이전트(`form_agent`)와 조합기(`pipeline`)는 목표금액 보고서
    입력(`ReportAIInput`) 하나만 알고 있었다. 매물별 보고서가 생기면서 같은
    파이프라인을 두 벌 복사할 이유가 없어졌다 — 복사하면 검증 규칙이 갈린다.

무엇을 담는가:
    "절 목록 / 절별 서술 지침 / 시스템 프롬프트 / 양식을 만드는 법 / 서술을
    검증하는 법 / 외부 전송 전에 검사할 원본"만 담는다. 파이프라인은 이것만
    보고 돈다.

왜 검증기까지 주입하는가:
    보고서 종류마다 **막아야 하는 오류가 다르다.** 목표금액 보고서는 부족액의
    귀속을 틀리는 것이 관찰된 오류였고, 매물 보고서는 매물별 결과를 섞는 것이
    구조적 위험이다. 공통 검증기 하나로 뭉개면 둘 다 놓친다.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.reports.templates.form import ReportForm
from app.reports.validation.numbers import VerificationResult


@dataclass(frozen=True)
class NarrationSpec:
    """한 종류의 보고서를 AI로 서술시키는 데 필요한 것 전부."""

    # (절 키, 절 제목). 구조화 출력 스키마와 순회 순서가 이것으로 정해진다.
    sections: tuple[tuple[str, str], ...]
    # 절 키 → 그 절에서 설명할 것. 모든 절 키에 값이 있어야 한다.
    guides: Mapping[str, str]
    system_prompt: str
    generation_rules: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    # 외부 AI에 나가기 전에 개인정보 검사를 받을 원본 JSON.
    egress_payload: Mapping[str, Any]
    # 채택된 서술만 채워 최종 양식을 만든다. None이면 빈 양식.
    build_form: Callable[[Mapping[str, str] | None], ReportForm]
    # (서술, 절 키) → 기계 검증 결과.
    verify: Callable[[str, str], VerificationResult]

    def __post_init__(self) -> None:
        if not self.sections:
            raise ValueError("narration spec must declare at least one section")
        keys = [key for key, _title in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("narration spec section keys must be unique")
        missing_guides = [key for key in keys if key not in self.guides]
        if missing_guides:
            # 지침 없는 절을 프롬프트에 실으면 AI가 그 칸을 아무렇게나 채운다.
            raise ValueError(f"narration guide is missing for: {', '.join(missing_guides)}")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _title in self.sections)


__all__ = ["NarrationSpec"]
