"""매물 보고서 서술 칸의 기계 검증.

핸드오프 문서 8항 4)가 요구한 확장이다. 공통 규칙(수치·날짜 금지, 결과에 없는
상품 금지)은 ``verify_narration_text``를 그대로 쓰고, 매물 보고서에만 있는
위험을 여기서 더한다.

무엇을 더 막는가:
    1. **매물을 특정해 말하는 것.** 매물명·주소·매물 번호를 서술 칸에서 아예
       금지한다. 문서가 요구한 "매물별 결과를 섞지 않았는지"를 사후에 판별하는
       것보다, 서술 칸에서 매물 지목을 없애 **섞일 수 없게** 만드는 쪽이 확실하다.
       매물별 값은 이미 수치 줄이 매물명과 함께 보여 주므로 잃는 정보가 없다.
    2. **승인·보장 표현.** SSOT §20이 요구하는 미보장 표시와 정면으로 충돌한다.
    3. **판정에 없는 긍정.** 구매 가능 판정이 하나도 없는데 구매 가능을 말하면
       위반이다. 전부 판정 불가면 가능·불가 어느 쪽도 단정할 수 없다.
    4. **누락을 해결한 것처럼 쓰는 것.** 결측이 남아 있는데 "확인할 것이 없다"고
       쓰면 사용자가 확인을 건너뛴다.

금액 대조는 왜 없는가:
    문서는 "AI가 쓴 모든 금액이 handoff에 존재하는 값인지"를 요구했다. 이 양식은
    서술 칸에 **금액을 아예 쓸 수 없게** 하므로 그보다 강한 규칙이 이미 걸려 있다.
"""

import re
from collections.abc import Iterable

from app.engines.affordability import AffordabilityVerdict
from app.reports.validation.numbers import (
    VerificationResult,
    Violation,
    verify_narration_text,
)
from app.schemas.property_report import PropertyReportAIInput

# "매물 3은", "매물3." 처럼 번호로 지목하는 것도 매물 특정이다.
_LISTING_INDEX = re.compile(r"매물\s*\d+")

# "승인됩니다", "승인 가능", "확정됩니다", "보장합니다" 계열.
_GUARANTEE = re.compile(
    r"승인\s*(?:이\s*)?(?:됩니다|된|되었|되며|가능)"
    r"|확정\s*(?:됩니다|입니다)"
    r"|보장\s*(?:합니다|됩니다|드립니다)"
)

_AFFORDABLE_CLAIMS: tuple[str, ...] = (
    "구매할 수 있",
    "구입할 수 있",
    "매수할 수 있",
    "구매가 가능",
    "구매 가능합니다",
    "구입이 가능",
)

_IMPOSSIBLE_CLAIMS: tuple[str, ...] = (
    "구매할 수 없",
    "구입할 수 없",
    "구매가 불가",
    "구입이 불가",
)

_RESOLVED_CLAIMS: tuple[str, ...] = (
    "모두 확인되었",
    "모두 확인됐",
    "누락된 정보는 없",
    "누락된 입력은 없",
    "추가로 확인할 사항은 없",
    "확인이 필요한 항목은 없",
)

_UNRESOLVED_VERDICTS = frozenset(
    {AffordabilityVerdict.UNKNOWN, AffordabilityVerdict.UNSUPPORTED}
)


def collect_loan_product_names(payload: PropertyReportAIInput) -> set[str]:
    """조달 후보로 선정된 상품명. 서술이 언급할 수 있는 상품의 전부다."""

    return {
        name.strip()
        for item in payload.handoff.items
        for name in item.selected_loan_products
        if name.strip()
    }


def collect_listing_identifiers(payload: PropertyReportAIInput) -> set[str]:
    """서술 칸에 나타나면 안 되는 매물 식별 문자열."""

    identifiers: set[str] = set()
    for item in payload.handoff.items:
        identifiers.add(item.listing_id.strip())
        if item.property_name and item.property_name.strip():
            identifiers.add(item.property_name.strip())
        if item.address_summary.strip():
            identifiers.add(item.address_summary.strip())
    return {value for value in identifiers if value}


def _phrase_violations(
    text: str,
    phrases: Iterable[str],
    *,
    kind: str,
    detail: str,
) -> list[Violation]:
    return [
        Violation(kind=kind, value=phrase, detail=detail)
        for phrase in phrases
        if phrase in text
    ]


def verify_property_narration(
    text: str,
    payload: PropertyReportAIInput,
    *,
    section_key: str | None = None,
) -> VerificationResult:
    """공통 규칙에 매물 보고서 전용 규칙을 더해 서술 칸을 검사한다."""

    base = verify_narration_text(
        text,
        known_names=collect_loan_product_names(payload),
        section_key=section_key,
        # 목표금액 보고서의 금지 표현표는 이 양식의 절 키와 맞지 않는다.
        forbidden_phrases={},
    )
    violations: list[Violation] = list(base.violations)

    for identifier in collect_listing_identifiers(payload):
        if identifier in text:
            violations.append(
                Violation(
                    kind="listing_reference",
                    value=identifier,
                    detail=(
                        "서술 칸에서 매물을 특정할 수 없습니다. 매물별 값은 수치 "
                        "줄이 매물명과 함께 보여 주며, 서술은 그 의미만 설명합니다."
                    ),
                )
            )
    for match in _LISTING_INDEX.findall(text):
        violations.append(
            Violation(
                kind="listing_reference",
                value=match,
                detail="서술 칸에서 매물 번호로 특정할 수 없습니다.",
            )
        )
    for match in _GUARANTEE.findall(text):
        violations.append(
            Violation(
                kind="guarantee",
                value=match,
                detail="대출 승인이나 결과를 보장하는 표현은 쓸 수 없습니다(SSOT §20).",
            )
        )

    verdicts = {item.verdict for item in payload.handoff.items}
    if AffordabilityVerdict.AFFORDABLE not in verdicts:
        violations.extend(
            _phrase_violations(
                text,
                _AFFORDABLE_CLAIMS,
                kind="verdict_overreach",
                detail="구매 가능으로 판정된 매물이 없는데 구매 가능을 서술했습니다.",
            )
        )
    if verdicts and verdicts <= _UNRESOLVED_VERDICTS:
        violations.extend(
            _phrase_violations(
                text,
                _IMPOSSIBLE_CLAIMS,
                kind="verdict_overreach",
                detail=(
                    "모든 매물이 판정 불가입니다. 판정 불가는 구매 불가가 아니므로 "
                    "불가능을 단정할 수 없습니다."
                ),
            )
        )
    if payload.missing_inputs:
        violations.extend(
            _phrase_violations(
                text,
                _RESOLVED_CLAIMS,
                kind="missing_input_overreach",
                detail="확인되지 않은 입력이 남아 있는데 모두 확인된 것처럼 서술했습니다.",
            )
        )

    return VerificationResult(
        ok=not violations,
        violations=tuple(violations),
        checked_numbers=base.checked_numbers,
        checked_names=base.checked_names,
        limitations=(
            "서술 칸의 수치·날짜·매물 식별자를 전면 금지합니다.",
            "매물 사이의 값 혼동은 매물 지목을 막아 구조적으로 차단합니다.",
            "문장의 인과 설명이 옳은지는 보증하지 않습니다 — 검증 에이전트가 보완합니다.",
        ),
    )


__all__ = [
    "collect_listing_identifiers",
    "collect_loan_product_names",
    "verify_property_narration",
]
