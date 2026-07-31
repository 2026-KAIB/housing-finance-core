"""매물별 보고서의 고정 양식.

목표금액 보고서(`form.py`)와 **같은 원칙**이다: 구조와 수치는 이 모듈이 확정하고
AI에게는 서술 칸만 맡긴다. 절 구성은 팀 핸드오프 문서 8항 2)의 권장 절을 따른다.

목표금액 양식과 무엇이 다른가:
    축이 다르다. 저쪽은 목표 하나에 대해 절이 나뉘고, 이쪽은 **매물 N건**이
    모든 절을 관통한다. 그래서 절마다 매물별 줄을 낸다.

매물 줄을 왜 잘라 내는가:
    검색 결과가 몇 건이 될지 이 모듈이 정하지 않는다. 서술 칸을 채우는 AI에게
    수백 줄을 넘기면 프롬프트가 길어지는 것보다 **줄을 섞을 위험**이 커진다.
    잘라 낼 때는 몇 건을 뺐는지 문서에 적는다 — 조용히 줄이면 "이게 전부"로 읽힌다.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.engines.affordability import AffordabilityVerdict
from app.reports.templates.form import FormSection, ReportForm
from app.schemas.property_affordability import PropertyAffordabilityAIItem
from app.schemas.property_report import PropertyReportAIInput
from app.schemas.simulation import SectionRunStatus

PROPERTY_FORM_SECTIONS: tuple[tuple[str, str], ...] = (
    ("search_and_data", "1. 검색 조건과 데이터 기준시점"),
    ("financial_diagnosis", "2. 사용자 금융진단 요약"),
    ("purchase_costs", "3. 매물별 총구매비용"),
    ("loan_funding", "4. 매물별 필요 대출과 조달 가능액"),
    ("affordability_verdicts", "5. 매물별 구매 가능성 판정"),
    ("monthly_burden", "6. 월 상환 부담과 구매 후 잉여현금"),
    ("stress_result", "7. 스트레스 상황 결과"),
    ("user_confirmations", "8. 누락 입력과 추가 확인사항"),
    ("comparison_summary", "9. 최종 비교 요약"),
)

# 한 절에 실을 매물 줄의 상한.
_MAX_LISTING_LINES = 10

_NOT_CALCULATED = "아직 계산하지 않았습니다."

_VERDICT_LABELS: dict[str, str] = {
    AffordabilityVerdict.AFFORDABLE.value: "구매 가능",
    AffordabilityVerdict.TIGHT.value: "가능하나 여유 없음",
    AffordabilityVerdict.SHORTFALL.value: "자금 부족",
    # 아래 둘은 "불가"가 아니라 "모름"이다. 라벨에서부터 갈라 둔다(§22.1).
    AffordabilityVerdict.UNKNOWN.value: "판정 불가(입력 부족)",
    AffordabilityVerdict.UNSUPPORTED.value: "판정 대상 아님(지원하지 않는 조건)",
}

_PROPERTY_TYPE_LABELS: dict[str, str] = {
    "APARTMENT": "아파트",
    "VILLA": "빌라·연립",
    "OFFICETEL": "오피스텔",
    "HOUSE": "단독·다가구",
}

_SORT_LABELS: dict[str, str] = {
    "PRICE_ASC": "가격 낮은 순",
    "UPDATED_DESC": "최근 갱신 순",
    "STATION_WALK_ASC": "역까지 도보 짧은 순",
}


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _won(value: object) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "확인되지 않음"
    return f"{int(parsed):,}원"


def _signed_won(value: object) -> str:
    """잉여현금처럼 음수가 의미를 갖는 값. 음수를 부호 없이 적으면 뒤집힌다."""
    parsed = _decimal(value)
    if parsed is None:
        return "확인되지 않음"
    return f"{int(parsed):+,}원"


def _verdict_label(verdict: AffordabilityVerdict) -> str:
    return _VERDICT_LABELS.get(verdict.value, verdict.value)


def _label(item: PropertyAffordabilityAIItem, index: int) -> str:
    """매물을 가리키는 짧은 이름. 이름이 없으면 주소로 대신한다."""
    name = (item.property_name or "").strip() or item.address_summary
    return f"매물 {index}. {name}"


def _needs_no_loan(item: PropertyAffordabilityAIItem) -> bool:
    """대출을 쓰지 않는 것이 **확인된** 경우.

    필요 대출금액이 0으로 산출됐으면 월 상환액도 스트레스 상환액도 0이다.
    엔진은 이 자리를 ``None``으로 두는데, 그대로 "확인되지 않음"으로 적으면
    확인된 사실을 모른다고 말하는 셈이다 — 모름을 0으로 뭉개지 않는 것과
    같은 이유로 **0을 모름으로 뭉개서도 안 된다.**
    """
    return item.required_loan_amount is not None and item.required_loan_amount == 0


@dataclass(frozen=True)
class _Listings:
    """절마다 반복하는 "앞 N건만, 나머지는 몇 건" 처리를 한 곳에 둔다."""

    shown: tuple[tuple[int, PropertyAffordabilityAIItem], ...] = field(
        default_factory=tuple
    )
    omitted: int = 0

    @property
    def tail(self) -> tuple[str, ...]:
        if not self.omitted:
            return ()
        return (
            f"- 위 목록은 검색 결과 앞 {len(self.shown)}건입니다. "
            f"나머지 {self.omitted}건은 이 보고서의 매물 목록 붙임과 계산 결과 "
            "JSON에 그대로 들어 있습니다.",
        )


def _listings(payload: PropertyReportAIInput) -> _Listings:
    items = payload.handoff.items
    shown = tuple(enumerate(items[:_MAX_LISTING_LINES], start=1))
    return _Listings(shown=shown, omitted=max(len(items) - len(shown), 0))


def _search_and_data(payload: PropertyReportAIInput) -> tuple[str, ...]:
    criteria = payload.criteria
    handoff = payload.handoff
    source = handoff.source
    floor = "하한 없음" if criteria.min_price_krw is None else _won(criteria.min_price_krw)
    ceiling = "상한 없음" if criteria.max_price_krw is None else _won(criteria.max_price_krw)
    lines = [
        f"- 검색 지역코드: {', '.join(criteria.region_codes) or '지정하지 않음'}",
        "- 매물 종류: "
        + (
            ", ".join(
                _PROPERTY_TYPE_LABELS.get(item.value, item.value)
                for item in criteria.property_types
            )
            or "전체"
        ),
        f"- 가격 범위: {floor} ~ {ceiling}",
    ]
    if criteria.max_station_walk_minutes is not None:
        lines.append(f"- 역까지 도보: {criteria.max_station_walk_minutes}분 이내")
    lines.append(f"- 정렬 기준: {_SORT_LABELS.get(criteria.sort.value, criteria.sort.value)}")
    lines.append(f"- 검색된 매물: {len(handoff.items)}건")
    lines.append(f"- 매물 데이터 기준시점: {handoff.data_as_of.isoformat()}")
    lines.append(f"- 계산 일시: {handoff.calculated_at.isoformat()}")
    lines.append(
        f"- 매물 출처: {source.source_name} ({source.source_type.value}, "
        f"버전 {source.source_version})"
    )
    if source.license_note:
        lines.append(f"- 출처 이용조건: {source.license_note}")
    return tuple(lines)


def _financial_diagnosis(payload: PropertyReportAIInput) -> tuple[str, ...]:
    section = payload.financial_diagnosis
    if section.run_status is not SectionRunStatus.COMPLETED or not section.facts:
        lines = [_NOT_CALCULATED]
        lines.extend(f"- {reason}" for reason in section.reasons)
        return tuple(lines)

    facts = dict(section.facts)
    diagnosis = facts.get("diagnosis")
    emergency = facts.get("emergency_fund")
    lines: list[str] = [f"- 진단 상태: {section.engine_status or facts.get('status')}"]
    if isinstance(diagnosis, dict):
        lines.append(f"- 안전 월 소득: {_won(diagnosis.get('safe_monthly_income'))}")
        lines.append(
            f"- 안전 월 필수지출: {_won(diagnosis.get('safe_monthly_essential_expense'))}"
        )
        lines.append(f"- 기존 월 상환액: {_won(diagnosis.get('monthly_debt_payment'))}")
        lines.append(f"- 안전 월 잉여자금: {_signed_won(diagnosis.get('safe_monthly_surplus'))}")
    if isinstance(emergency, dict):
        lines.append(f"- 비상자금 목표액: {_won(emergency.get('target_amount'))}")
        shortfall = _decimal(emergency.get("shortfall_amount"))
        if shortfall is not None and shortfall > 0:
            lines.append(f"- 비상자금 부족액: {_won(shortfall)}")
        lines.append(
            "- 비상자금을 채우고 남는 유동자산: "
            f"{_won(emergency.get('usable_liquid_assets_after_target'))}"
        )
    lines.extend(f"- {reason}" for reason in section.reasons)
    return tuple(lines)


def _purchase_costs(payload: PropertyReportAIInput) -> tuple[str, ...]:
    listings = _listings(payload)
    if not listings.shown:
        return ("- 검색된 매물이 없어 총구매비용을 산출하지 않았습니다.",)
    lines: list[str] = []
    for index, item in listings.shown:
        total = (
            _won(item.total_purchase_cost)
            if item.total_purchase_cost is not None
            # 총액을 확정하지 못했을 때 최소액을 총액인 것처럼 적지 않는다.
            else f"확인되지 않음 (확인된 최소 {_won(item.minimum_total_purchase_cost)})"
        )
        lines.append(
            f"- {_label(item, index)}: 매매가 {_won(item.price_krw)}, "
            f"총구매비용 {total}"
        )
    lines.append(
        "- 총구매비용은 매매가에 취득세·중개보수 등 확인된 부대비용을 더한 금액입니다."
    )
    lines.extend(listings.tail)
    return tuple(lines)


def _loan_funding(payload: PropertyReportAIInput) -> tuple[str, ...]:
    listings = _listings(payload)
    if not listings.shown:
        return ("- 검색된 매물이 없어 필요 대출을 산출하지 않았습니다.",)
    lines: list[str] = [
        f"- 구매 전 사용 가능 유동자산: "
        f"{_won(listings.shown[0][1].usable_liquid_assets_before_purchase)}",
    ]
    for index, item in listings.shown:
        if _needs_no_loan(item):
            lines.append(
                f"- {_label(item, index)}: 필요 대출 없음 — 자기자금으로 조달합니다."
            )
            continue
        products = ", ".join(item.selected_loan_products) or "선정된 상품 없음"
        gap = (
            f", 부족액 {_won(item.funding_gap)}"
            if item.funding_gap is not None and item.funding_gap > 0
            else ""
        )
        lines.append(
            f"- {_label(item, index)}: 필요 대출 {_won(item.required_loan_amount)}, "
            f"조달 가능액 {_won(item.loan_funding_amount)}{gap} / 조달 상품: {products}"
        )
    lines.extend(listings.tail)
    return tuple(lines)


def _affordability_verdicts(payload: PropertyReportAIInput) -> tuple[str, ...]:
    listings = _listings(payload)
    if not listings.shown:
        return ("- 검색된 매물이 없어 구매 가능성을 판정하지 않았습니다.",)
    lines: list[str] = []
    for index, item in listings.shown:
        lines.append(f"- {_label(item, index)}: {_verdict_label(item.verdict)}")
        for reason in item.reasons:
            lines.append(f"  - 사유: {reason}")
        for missing in item.missing_inputs:
            lines.append(f"  - 확인 필요: {missing}")
    lines.append(
        "- 판정 불가와 판정 대상 아님은 구매할 수 없다는 뜻이 아니라 "
        "이 계산으로는 판단하지 못했다는 뜻입니다."
    )
    lines.extend(listings.tail)
    return tuple(lines)


def _monthly_burden(payload: PropertyReportAIInput) -> tuple[str, ...]:
    listings = _listings(payload)
    if not listings.shown:
        return ("- 검색된 매물이 없어 월 상환 부담을 산출하지 않았습니다.",)
    lines: list[str] = []
    for index, item in listings.shown:
        payment = (
            "월 상환액 없음(대출 미사용)"
            if _needs_no_loan(item)
            else f"월 상환액 {_won(item.monthly_loan_payment)}"
        )
        lines.append(
            f"- {_label(item, index)}: {payment}, "
            f"구매 후 월 잉여현금 {_signed_won(item.post_purchase_monthly_surplus)}"
        )
    lines.extend(listings.tail)
    return tuple(lines)


def _stress_result(payload: PropertyReportAIInput) -> tuple[str, ...]:
    listings = _listings(payload)
    if not listings.shown:
        return ("- 검색된 매물이 없어 스트레스 결과를 산출하지 않았습니다.",)
    lines: list[str] = []
    known = 0
    for index, item in listings.shown:
        if item.stress_monthly_surplus is None:
            if _needs_no_loan(item):
                lines.append(
                    f"- {_label(item, index)}: 대출을 쓰지 않아 금리 상승 "
                    "스트레스가 적용되지 않습니다."
                )
                continue
            lines.append(f"- {_label(item, index)}: 스트레스 결과 확인되지 않음")
            continue
        known += 1
        lines.append(
            f"- {_label(item, index)}: 스트레스 조건 월 잉여현금 "
            f"{_signed_won(item.stress_monthly_surplus)}"
        )
    if known:
        lines.append(
            "- 스트레스 조건은 규제 심사 기준이 아니라 금리가 오를 때 생활이 "
            "유지되는지 보는 내부 점검입니다."
        )
    lines.extend(listings.tail)
    return tuple(lines)


def _user_confirmations(payload: PropertyReportAIInput) -> tuple[str, ...]:
    lines: list[str] = []
    missing = payload.missing_inputs
    if missing:
        lines.append("확인이 필요한 입력:")
        lines.extend(f"- {name}" for name in missing)
        lines.append("")
    else:
        lines.append("- 이 계산에서 누락으로 기록된 입력은 없습니다.")
    assumptions = tuple(
        dict.fromkeys(note for item in payload.handoff.items for note in item.assumptions)
    )
    if assumptions:
        lines.append("계산에 사용한 가정:")
        lines.extend(f"- {note}" for note in assumptions)
        lines.append("")
    lines.append("매물과 상품에서 직접 확인할 것:")
    lines.append("- 등기부상 권리관계와 선순위 채권 유무")
    lines.append("- 실제 취득세율을 좌우하는 주택 수·조정대상지역 해당 여부")
    lines.append("- 대출 상품의 우대금리 조건과 자유텍스트 자격 세부조건")
    return tuple(lines)


def _verdict_counts(items: Sequence[PropertyAffordabilityAIItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.verdict.value] = counts.get(item.verdict.value, 0) + 1
    return counts


def _comparison_summary(payload: PropertyReportAIInput) -> tuple[str, ...]:
    items = payload.handoff.items
    if not items:
        return ("- 검색 조건에 맞는 매물이 없습니다.",)
    counts = _verdict_counts(items)
    lines = [f"- 검색된 매물: {len(items)}건"]
    for verdict in AffordabilityVerdict:
        count = counts.get(verdict.value, 0)
        if count:
            lines.append(f"- {_VERDICT_LABELS.get(verdict.value, verdict.value)}: {count}건")
    lines.append(
        "- 위 순서는 검색 정렬 기준에 따른 나열이며 추천 순위가 아닙니다. "
        "이 보고서는 매물 사이의 우열을 정하지 않습니다."
    )
    return tuple(lines)


_BUILDERS = {
    "search_and_data": _search_and_data,
    "financial_diagnosis": _financial_diagnosis,
    "purchase_costs": _purchase_costs,
    "loan_funding": _loan_funding,
    "affordability_verdicts": _affordability_verdicts,
    "monthly_burden": _monthly_burden,
    "stress_result": _stress_result,
    "user_confirmations": _user_confirmations,
    "comparison_summary": _comparison_summary,
}

_DISCLAIMERS = (
    "이 보고서는 계산 결과를 설명한 것이며 대출 승인이나 실제 적용금리를 보장하지 않습니다.",
    "매물 정보는 표시된 기준시점의 스냅샷이며 실제 거래 가능 여부는 확인이 필요합니다.",
    "판정 불가와 판정 대상 아님은 구매 불가가 아니며, 확인하면 결과가 달라질 수 있습니다.",
    "수치는 계산 엔진이 산출했고 문장 설명만 AI가 작성했습니다.",
)


def build_property_report_form(
    payload: PropertyReportAIInput,
    *,
    narrations: dict[str, str] | None = None,
) -> ReportForm:
    """수치를 확정한 매물 보고서 양식을 만든다. ``narrations``가 있으면 서술을 채운다."""

    resolved = narrations or {}
    handoff = payload.handoff
    headline = (
        "# 매물별 구매 가능성 보고서\n"
        f"- 산출 기준일: {payload.as_of.isoformat()}\n"
        f"- 검색 스냅샷: {handoff.search_snapshot_id}\n"
        f"- 검색된 매물: {len(handoff.items)}건"
    )
    sections = tuple(
        FormSection(
            key=key,
            title=title,
            figures=_BUILDERS[key](payload),
            narration=resolved.get(key),
        )
        for key, title in PROPERTY_FORM_SECTIONS
    )
    return ReportForm(
        headline=headline,
        sections=sections,
        policy_sources=payload.policy_sources,
        disclaimers=_DISCLAIMERS,
    )


__all__ = [
    "PROPERTY_FORM_SECTIONS",
    "build_property_report_form",
]
