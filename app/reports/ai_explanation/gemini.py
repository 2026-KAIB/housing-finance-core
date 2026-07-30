"""Gemini API 얇은 클라이언트.

목적:
    보고서 설명 문장을 생성한다. 계산은 하지 않는다.
기능:
    ``generateContent`` REST 엔드포인트를 ``httpx``로 호출한다. 이미 의존성에
    있는 클라이언트라 새 패키지를 들이지 않는다.
근거:
    키는 **환경변수·`.env`에서만** 읽는다(`app/core/config.py`). 코드·테스트·
    픽스처에 키 값을 넣지 않으며, 실패 사유를 담은 결과를 돌려주고 예외로
    파이프라인을 끊지 않는다 — 고정 템플릿 보고서는 계속 제공돼야 한다.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class GenerationResult:
    """생성 결과. ``text``가 ``None``이면 실패이고 ``error``에 사유가 있다."""

    text: str | None
    model: str
    error: str | None = None
    # 호출 흔적. 보고서에 "AI 설명 없음" 사유를 남길 때 쓴다.
    request_notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.text is not None


class ExplanationClient(Protocol):
    """설명 생성기 인터페이스.

    에이전트가 이 프로토콜에만 의존하므로 테스트는 네트워크 없이 가짜 구현을
    넣을 수 있고, 제공자를 바꿔도 에이전트를 고치지 않는다.
    """

    def generate(self, *, system_prompt: str, user_prompt: str) -> GenerationResult: ...


class GeminiClient:
    """``generateContent`` 호출자."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.gemini_api_key)

    def generate(self, *, system_prompt: str, user_prompt: str) -> GenerationResult:
        model = self._settings.gemini_model
        if not self.configured:
            return GenerationResult(
                text=None,
                model=model,
                error="GEMINI_API_KEY가 설정되지 않았습니다.",
                request_notes=(
                    "환경변수 GEMINI_API_KEY를 설정하면 AI 설명이 추가됩니다.",
                ),
            )

        url = f"{self._settings.gemini_base_url}/models/{model}:generateContent"
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                # 설명문이므로 창작 여지를 낮춘다. 숫자를 지어내는 경향을 줄이는
                # 첫 번째 방어선이고, 두 번째가 `validation/numbers.py`다.
                "temperature": 0.0,
                "maxOutputTokens": 4096,
                # 2.5 계열은 내부 thinking 토큰이 maxOutputTokens를 함께 소비한다.
                # 켜 둔 상태로 2048을 주면 본문이 한 문장 만에 잘린다 — 실제로
                # "350,00"처럼 숫자 중간에서 끊긴 보고서가 나왔다. 계산은 이미
                # 끝났고 여기서는 서술만 하므로 추론 예산이 필요하지 않다.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        try:
            response = httpx.post(
                url,
                json=body,
                # 키를 URL 쿼리스트링에 넣지 않는다. 쿼리는 로그·리퍼러에 남는다.
                headers={"x-goog-api-key": self._settings.gemini_api_key or ""},
                timeout=self._settings.gemini_timeout_seconds,
            )
        except httpx.HTTPError as error:  # 네트워크·타임아웃
            return GenerationResult(
                text=None,
                model=model,
                error=f"Gemini 호출에 실패했습니다: {type(error).__name__}",
            )

        if response.status_code != 200:
            # 본문에 키가 실릴 이유는 없지만, 응답 전체를 그대로 남기지 않는다.
            return GenerationResult(
                text=None,
                model=model,
                error=f"Gemini가 HTTP {response.status_code}을 반환했습니다.",
            )

        text, finish_reason = _first_candidate(response.json())
        if text is None:
            return GenerationResult(
                text=None,
                model=model,
                error="Gemini 응답에서 본문을 찾지 못했습니다.",
            )
        if finish_reason not in (None, "STOP"):
            # 잘린 본문을 채택하면 숫자가 중간에서 끊긴 보고서가 나간다. 검증기는
            # "지어낸 수"를 잡지만 "끊긴 수"는 패턴에 맞지 않아 그냥 통과한다.
            # 그래서 여기서 실패로 처리한다.
            return GenerationResult(
                text=None,
                model=model,
                error=f"Gemini 응답이 정상 종료되지 않았습니다(finishReason={finish_reason}).",
            )
        return GenerationResult(text=text, model=model)


def _first_candidate(payload: object) -> tuple[str | None, str | None]:
    """``candidates[0]``의 본문과 종료 사유를 함께 돌려준다."""
    if not isinstance(payload, dict):
        return None, None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None, None
    first = candidates[0]
    if not isinstance(first, dict):
        return None, None
    finish_reason = first.get("finishReason")
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None, finish_reason if isinstance(finish_reason, str) else None
    chunks = [
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    joined = "".join(chunks).strip()
    return (joined or None), (finish_reason if isinstance(finish_reason, str) else None)


__all__ = ["ExplanationClient", "GeminiClient", "GenerationResult"]
