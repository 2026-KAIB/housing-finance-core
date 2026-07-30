"""AI가 만들어낸 숫자·상품명을 걸러내는 사후 검증기.

목적:
    ``reports/README``의 4단계다. AI는 계산 결과를 **설명**만 할 수 있고 숫자·
    상품명·상태를 바꿀 수 없다. 그 규칙을 문장 생성 이후에 기계적으로 확인한다.
기능:
    생성된 문장에서 금액·비율·상품명을 뽑아 계산 결과에 실제로 있는지 대조한다.
    하나라도 근거가 없으면 위반으로 보고하고, 호출자는 그 문장을 채택하지 않는다.
근거:
    SSOT §20 "AI는 금액·점수·상품 순위를 결정하지 않는다". 프롬프트로 부탁하는
    것만으로는 보장이 되지 않으므로 출력 쪽에 검사를 둔다.

무엇을 잡고 무엇을 못 잡는가:
    - 잡는다: 천단위 쉼표가 있는 수, ``원``/``%``가 붙은 수, ISO 날짜, 상품명.
    - 안 잡는다: 쉼표·단위 없는 1,000 미만 정수. "세 가지", "9개 시나리오"처럼
      산문에 쓰이는 수까지 위반으로 만들면 거짓 양성이 너무 많아진다. 대신
      **금액과 비율은 반드시 단위와 함께 쓰라고** 프롬프트에서 요구한다.
    그래서 이 검증기는 "숫자를 지어내지 못하게" 하는 장치이고, 문장의 사실관계
    전체를 보증하지는 않는다. 그 한계를 결과에 함께 담는다.
"""

import re
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


def collect_source_numbers(payload: ReportAIInput) -> set[Decimal]:
    """계산 결과에 실제로 존재하는 수의 집합.

    비율은 0~1로 저장되지만 문장에서는 퍼센트로 쓰이므로 ``×100`` 형태도 함께
    허용한다. 반대로 금액은 반올림해 쓰이므로 정수로 내린 값도 함께 넣는다.

    **문장 속에 서식화돼 들어 있는 수도 함께 모은다.** 엔진의 ``reasons``에는
    "월 최소 Buffer 대비 521,999원이 부족합니다"처럼 금액이 문장으로 박혀 있고,
    AI가 그 근거를 인용하는 것은 정당하다. 숫자 필드만 모았을 때 실제로 그런
    정당한 인용이 위반으로 잡혔다.
    """
    numbers: set[Decimal] = set()

    def _add(value: Decimal) -> None:
        numbers.add(value)
        numbers.add(value.to_integral_value())
        if 0 < abs(value) <= 1:
            numbers.add(value * 100)
            numbers.add((value * 100).to_integral_value())

    for _key, item in _walk(payload.to_json_dict()):
        if isinstance(item, bool) or item is None:
            continue
        if not isinstance(item, (int, float, str)):
            continue
        text = str(item)
        whole = _to_decimal(text)
        if whole is not None:
            _add(whole)
            continue
        # 값 전체가 수가 아니면 문장으로 보고 서식화된 수를 뽑는다.
        for embedded in _extract_numbers(text):
            parsed = _to_decimal(embedded)
            if parsed is not None:
                _add(parsed)
    return numbers


def collect_source_dates(payload: ReportAIInput) -> set[str]:
    """계산 결과에 등장하는 모든 ISO 날짜.

    기준일·목표일만 허용하면 안 된다. ``policy_sources``에는 규제 시행일이
    문장으로 들어 있고(예: "「가계부채 관리 강화 방안」(2025-06-27)"), AI가 근거
    날짜를 인용하는 것은 §19가 요구하는 바람직한 서술이다. 실제로 기준일만
    허용했을 때 정상 인용이 위반으로 잡혔다.
    """
    dates = {
        payload.as_of.isoformat(),
        payload.goal.target_date.isoformat(),
    }
    for _key, item in _walk(payload.to_json_dict()):
        if isinstance(item, str):
            dates.update(_ISO_DATE.findall(item))
    return dates


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


def verify_explanation(text: str, payload: ReportAIInput) -> VerificationResult:
    """생성된 문장이 계산 결과 안에 머물렀는지 확인한다."""
    source_numbers = collect_source_numbers(payload)
    source_names = collect_source_names(payload)
    source_dates = collect_source_dates(payload)

    violations: list[Violation] = []

    numbers = _extract_numbers(text)
    for raw in numbers:
        value = _to_decimal(raw)
        if value is None:
            continue
        if any(abs(value - known) <= _AMOUNT_TOLERANCE for known in source_numbers):
            continue
        violations.append(
            Violation(
                kind="number",
                value=raw,
                detail="계산 결과에 없는 수입니다. AI가 만들어낸 값일 수 있습니다.",
            )
        )

    for iso in _ISO_DATE.findall(text):
        if iso in source_dates:
            continue
        violations.append(
            Violation(
                kind="date",
                value=iso,
                detail="계산 결과에 없는 날짜입니다.",
            )
        )

    unknown_names = _mentions_unknown_product(text, source_names)
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
        checked_names=len(unknown_names) + len(source_names),
    )


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


def _forbidden_phrase_violations(text: str, section_key: str | None) -> list[Violation]:
    if section_key is None:
        return []
    return [
        Violation(kind="misattribution", value=phrase, detail=detail)
        for phrase, detail in _FORBIDDEN_PHRASES.get(section_key, ())
        if phrase in text
    ]


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
    violations: list[Violation] = _forbidden_phrase_violations(text, section_key)
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

    source_names = collect_source_names(payload)
    unknown_names = _mentions_unknown_product(text, source_names)
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
        checked_names=len(unknown_names) + len(source_names),
        limitations=(
            "서술 칸의 수치·날짜를 전면 금지합니다.",
            "수치 없는 귀속 오류는 관찰된 표현만 막습니다(_FORBIDDEN_PHRASES).",
            "문장의 인과 설명이 옳은지는 보증하지 않습니다 — 검증 에이전트가 보완합니다.",
        ),
    )


__all__ = [
    "VerificationResult",
    "Violation",
    "collect_source_dates",
    "collect_source_names",
    "collect_source_numbers",
    "verify_explanation",
]
