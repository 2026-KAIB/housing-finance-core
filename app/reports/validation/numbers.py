"""AI 서술이 계산 결과 밖으로 나가지 않았는지 검사한다.

목적:
    ``reports/README``의 4단계다. AI는 계산 결과를 **설명**만 할 수 있고 숫자·
    상품명·상태를 바꿀 수 없다. 프롬프트로 부탁하는 것만으로는 보장이 되지
    않으므로 출력 쪽에 기계 검사를 둔다(SSOT §20).

기능:
    고정 양식의 서술 칸을 검사한다. 수치는 엔진이 렌더링하므로 서술 칸에 수치가
    있을 이유가 없다 — **있으면 위반**이다. 이 규칙이 "값은 맞고 기준만 틀린"
    귀속 오류를 구조적으로 없앤다.

한계와 그 보완:
    수치 없이도 귀속을 틀릴 수 있다("표시된 부족액은 목표 금액 대비 부족한
    금액입니다"에는 숫자가 없지만 기준이 틀렸다). 실제 검증 에이전트에게 물었을 때
    이 문장을 OK로 판정하는 것을 확인했으므로, **관찰된 오류는 여기서 기계가
    막는다**(``_FORBIDDEN_PHRASES``). 아직 모르는 오류는 검증 에이전트가 찾는다.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.schemas.report import ReportAIInput

# 1,234 / 1,234,567원 / 3.5% / 40 % 처럼 단위나 쉼표가 붙은 수만 검사 대상이다.
_MEASURED_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(원|%|퍼센트)|"
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?)"
)
# `\b`는 한글 앞에서 깨진다("2030-01-01까지"의 끝에는 경계가 없다). 숫자
# 룩어라운드를 써야 한글이 붙은 날짜도 잡힌다.
_ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
# 금액은 원 단위 정수로 비교한다. 이분탐색 결과에 소수점이 남아 있어(문제 1 §남은 것)
# 문자열 그대로 비교하면 표시용 반올림과 어긋나기 때문이다.
_AMOUNT_TOLERANCE = Decimal("1")


@dataclass(frozen=True)
class Violation:
    kind: str
    value: str
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    violations: tuple[Violation, ...] = field(default_factory=tuple)
    checked_numbers: int = 0
    checked_names: int = 0
    limitations: tuple[str, ...] = (
        "쉼표·단위 없는 1,000 미만 정수는 검사하지 않습니다.",
        "숫자 출처만 확인하며 문장의 인과 설명이 옳은지는 보증하지 않습니다.",
    )


def _walk(value: object, key: str = ""):
    """(마지막 키, 값)을 훑는다.

    리스트 원소도 **부모 키와 함께** 내보내야 한다. ``reasons``·``policy_sources``는
    문자열 리스트인데, 원소를 내보내지 않으면 그 안에 서식화돼 들어 있는 금액과
    시행일을 전부 놓친다 — 실제로 그 때문에 AI가 근거 문장에서 정확히 인용한
    "521,999원"이 "지어낸 수"로 잡혔다.
    """
    if isinstance(value, dict):
        for child_key, item in value.items():
            yield child_key, item
            yield from _walk(item, child_key)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield key, item
            yield from _walk(item, key)


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _extract_numbers(text: str) -> list[str]:
    found: list[str] = []
    for match in _MEASURED_NUMBER.finditer(text):
        found.append(match.group(1) or match.group(3))
    return [item for item in found if item]


def collect_source_names(payload: ReportAIInput) -> set[str]:
    """계산 결과에 등장하는 상품명·옵션명."""
    names: set[str] = set()
    for key, item in _walk(payload.to_json_dict()):
        if isinstance(item, str) and key in {
            "product_name",
            "option_name",
            "institution_name",
        }:
            names.add(item.strip())
    return names


def _mentions_unknown_product(text: str, known: set[str]) -> list[str]:
    """"KB"로 시작하는 상품명처럼 보이는 토큰 중 계산 결과에 없는 것.

    일반 명사를 상품명으로 오인하지 않도록 금융기관 접두사가 붙은 경우만 본다.
    """
    candidates = re.findall(
        r"(?:KB|국민|하나|신한|우리|농협|카카오|토스)[\w가-힣·()\s]{1,30}", text
    )
    unknown: list[str] = []
    for candidate in candidates:
        cleaned = candidate.strip().rstrip("의은는이가을를에서와과,.")
        if not cleaned:
            continue
        if any(cleaned in name or name in cleaned for name in known):
            continue
        unknown.append(cleaned)
    return unknown


# 절별 금지 표현. **실제로 관찰된 오류에서 자란 목록이며 완전하지 않다.**
# 여기 있는 것은 "LLM 판정자가 놓치는 것을 확인한" 항목이다 — 아는 오류는 기계로
# 막고, 판정 에이전트는 아직 모르는 오류를 찾는 데 쓴다.
#
# 각 항목: (금지 표현, 왜 틀렸는지)
_FORBIDDEN_PHRASES: dict[str, tuple[tuple[str, str], ...]] = {
    "shortfall_and_extension": (
        (
            "목표 금액 대비",
            "부족액의 기준은 목표 금액이 아니라 필요 대출금액입니다. "
            "이렇게 쓰면 자기자본을 뺀 금액을 목표 금액과 비교한 것처럼 읽힙니다.",
        ),
        (
            "목표금액 대비",
            "부족액의 기준은 목표 금액이 아니라 필요 대출금액입니다.",
        ),
    ),
    "rates_and_policy": (
        (
            "심사용 금리로 상환",
            "심사용 금리는 한도 산정에만 쓰이며 실제 상환액 계산에 쓰이지 않습니다.",
        ),
    ),
}


def _forbidden_phrase_violations(
    text: str,
    section_key: str | None,
    forbidden: Mapping[str, tuple[tuple[str, str], ...]],
) -> list[Violation]:
    if section_key is None:
        return []
    return [
        Violation(kind="misattribution", value=phrase, detail=detail)
        for phrase, detail in forbidden.get(section_key, ())
        if phrase in text
    ]


def verify_narration_text(
    text: str,
    *,
    known_names: set[str],
    section_key: str | None = None,
    forbidden_phrases: Mapping[str, tuple[tuple[str, str], ...]] = _FORBIDDEN_PHRASES,
) -> VerificationResult:
    """보고서 종류와 무관한 서술 칸 공통 검사.

    ``verify_narration``이 목표금액 보고서 입력에서 상품명을 모아 이 함수를
    부른다. 매물 보고서처럼 입력 계약이 다른 쪽은 자기 상품명 집합과 자기
    금지 표현표를 넘겨 같은 규칙을 쓴다 — 규칙을 복사하면 두 벌이 갈린다.
    """
    violations: list[Violation] = _forbidden_phrase_violations(
        text, section_key, forbidden_phrases
    )
    numbers = _extract_numbers(text)
    for raw in numbers:
        violations.append(
            Violation(
                kind="number_in_narration",
                value=raw,
                detail=(
                    "서술 칸에는 수치를 쓸 수 없습니다. 수치는 계산 엔진이 "
                    "표시하며, 서술은 그 의미만 설명합니다."
                ),
            )
        )
    for iso in _ISO_DATE.findall(text):
        violations.append(
            Violation(
                kind="date_in_narration",
                value=iso,
                detail="서술 칸에는 날짜를 쓸 수 없습니다.",
            )
        )

    unknown_names = _mentions_unknown_product(text, known_names)
    for name in unknown_names:
        violations.append(
            Violation(
                kind="product_name",
                value=name,
                detail="종합추천 결과에 없는 상품을 언급했습니다.",
            )
        )

    return VerificationResult(
        ok=not violations,
        violations=tuple(violations),
        checked_numbers=len(numbers),
        checked_names=len(unknown_names) + len(known_names),
        limitations=(
            "서술 칸의 수치·날짜를 전면 금지합니다.",
            "수치 없는 귀속 오류는 관찰된 표현만 막습니다(_FORBIDDEN_PHRASES).",
            "문장의 인과 설명이 옳은지는 보증하지 않습니다 — 검증 에이전트가 보완합니다.",
        ),
    )


def verify_narration(
    text: str,
    payload: ReportAIInput,
    *,
    section_key: str | None = None,
) -> VerificationResult:
    """고정 양식의 **서술 칸**을 검사한다. 수치를 아예 허용하지 않는다.

    ``verify_explanation``보다 강한 규칙이다. 자유 서술에서는 "그 수가 계산 결과에
    있는가"만 볼 수 있어서, 값은 맞고 **귀속만 틀린** 문장을 잡지 못한다 — 실제로
    "목표 금액 대비 66,479,492원 부족"(실은 필요 대출금액 대비)이 통과했다.

    고정 양식에서는 수치를 엔진이 렌더링하므로 서술 칸에 수치가 있을 이유가 없다.
    그래서 "있으면 위반"으로 바꾼다.

    다만 **수치 없이도 귀속을 틀릴 수 있다.** "표시된 부족액은 목표 금액 대비
    부족한 금액입니다"에는 숫자가 없지만 기준이 틀렸다. 검증 에이전트(LLM)에게
    물어봤을 때 이 문장을 OK로 판정하는 것을 확인했으므로, 아는 오류는
    ``_FORBIDDEN_PHRASES``로 기계가 막는다.
    """
    return verify_narration_text(
        text,
        known_names=collect_source_names(payload),
        section_key=section_key,
    )


__all__ = [
    "VerificationResult",
    "Violation",
    "collect_source_names",
    "verify_narration",
    "verify_narration_text",
]
