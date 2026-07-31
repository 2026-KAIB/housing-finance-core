"""매물별 보고서의 인쇄용 정식 문서 렌더러.

`official.py`와 같은 원칙이다 — 문서번호·관인·"승인"을 넣지 않고, 발행 주체를
서비스로 밝히고, §20의 미보장 문구를 말미에 싣는다. 스타일시트도 같은 것을
쓴다(`PRINT_STYLE`). 두 문서가 다르게 보이면 같은 서비스의 산출물로 읽히지 않는다.

텍스트 양식과 무엇이 다른가:
    양식(`property_form.py`)은 서술 칸을 채우는 AI에게 넘길 것이라 매물 줄을
    앞 몇 건으로 자른다. 인쇄 문서는 사람이 보는 것이므로 **전 건**을 총괄표에
    싣는다. 자른 목록만 남기면 문서가 검색 결과 전체를 대표하지 못한다.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html import escape

from app.engines.affordability import AffordabilityVerdict
from app.reports.ai_explanation.pipeline import FinalReport
from app.reports.templates.official import PRINT_STYLE
from app.schemas.property_affordability import PropertyAffordabilityAIItem
from app.schemas.property_report import PropertyReportAIInput
from app.schemas.simulation import SectionRunStatus

_UNKNOWN = '<span class="missing">확인되지 않음</span>'

# 양식(`property_form.py`)과 **같은 표를 쓴다.** 두 곳이 갈리면 같은 판정에
# 다른 이름이 붙는다.
_VERDICT_LABELS: dict[str, str] = {
    AffordabilityVerdict.AFFORDABLE.value: "구매 가능",
    AffordabilityVerdict.TIGHT.value: "가능하나 여유 없음",
    AffordabilityVerdict.SHORTFALL.value: "자금 부족",
    AffordabilityVerdict.UNKNOWN.value: "판정 불가(입력 부족)",
    AffordabilityVerdict.UNSUPPORTED.value: "판정 대상 아님",
}


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _won(value: object) -> str:
    number = _decimal(value)
    if number is None:
        return _UNKNOWN
    return f"{number.quantize(Decimal('1'), rounding=ROUND_HALF_UP):,}원"


def _signed_won(value: object) -> str:
    number = _decimal(value)
    if number is None:
        return _UNKNOWN
    return f"{number.quantize(Decimal('1'), rounding=ROUND_HALF_UP):+,}원"


def _rows(*pairs: tuple[str, str]) -> str:
    return "".join(
        f'<tr><th class="rowhead">{escape(label)}</th><td>{value}</td></tr>'
        for label, value in pairs
    )


def _masthead(payload: PropertyReportAIInput) -> str:
    handoff = payload.handoff
    source = handoff.source
    return (
        '<div class="masthead"><dl>'
        "<dt>보고서 종류</dt><dd>매물별 구매 가능성 산출 결과</dd>"
        f"<dt>산출 기준일</dt><dd>{escape(payload.as_of.isoformat())}</dd>"
        f"<dt>산출 일시</dt><dd>{escape(handoff.calculated_at.isoformat())}</dd>"
        f"<dt>검색 스냅샷</dt><dd>{escape(str(handoff.search_snapshot_id))}</dd>"
        f"<dt>매물 기준시점</dt><dd>{escape(handoff.data_as_of.isoformat())}</dd>"
        f"<dt>매물 출처</dt><dd>{escape(source.source_name)} "
        f"({escape(source.source_type.value)}, 버전 {escape(source.source_version)})</dd>"
        f"<dt>검색된 매물</dt><dd>{len(handoff.items)}건</dd>"
        f"<dt>계약 버전</dt><dd>{escape(payload.schema_version)}</dd>"
        "</dl></div>"
    )


def _toc(narrated_titles: tuple[str, ...]) -> str:
    items = ["1. 매물별 산출 결과 총괄"]
    items.extend(narrated_titles)
    items.extend(["붙임 1. 적용 규제·정책 근거", "붙임 2. 확인되지 않은 항목"])
    body = "".join(f"<li>{escape(title)}</li>" for title in items)
    return f'<section class="toc"><h2>목차</h2><ul>{body}</ul></section>'


def _listing_name(item: PropertyAffordabilityAIItem) -> str:
    return (item.property_name or "").strip() or item.address_summary


def _overview(payload: PropertyReportAIInput) -> str:
    items = payload.handoff.items
    if not items:
        return (
            "<h2>1. 매물별 산출 결과 총괄</h2>"
            "<p>검색 조건에 맞는 매물이 없습니다. 조건을 넓히면 결과가 달라질 수 있습니다.</p>"
        )
    rows = ""
    for index, item in enumerate(items, start=1):
        total = (
            _won(item.total_purchase_cost)
            if item.total_purchase_cost is not None
            # 확정하지 못한 총액 자리에 최소액을 넣지 않는다. 넣으면 확정된
            # 값으로 읽히고, 실제 총액은 그보다 크다.
            else f"{_UNKNOWN}<br><small>최소 {_won(item.minimum_total_purchase_cost)}</small>"
        )
        verdict = _VERDICT_LABELS.get(item.verdict.value, item.verdict.value)
        # 필요 대출금액이 0으로 산출됐으면 월 상환액도 0이다. 엔진이 그 자리를
        # 비워 두더라도 "확인되지 않음"으로 적으면 확인된 사실을 모른다고 적는 셈이다.
        no_loan = item.required_loan_amount is not None and item.required_loan_amount == 0
        payment = "없음" if no_loan else _won(item.monthly_loan_payment)
        rows += (
            "<tr>"
            f'<td class="mid">{index}</td>'
            f"<td>{escape(_listing_name(item))}<br>"
            f"<small>{escape(item.address_summary)}</small></td>"
            f'<td class="num">{_won(item.price_krw)}</td>'
            f'<td class="num">{total}</td>'
            f'<td class="num">{_won(item.required_loan_amount)}</td>'
            f'<td class="num">{_won(item.loan_funding_amount)}</td>'
            f'<td class="num">{_won(item.funding_gap)}</td>'
            f'<td class="num">{payment}</td>'
            f'<td class="num">{_signed_won(item.post_purchase_monthly_surplus)}</td>'
            f'<td class="mid">{escape(verdict)}</td>'
            "</tr>"
        )
    counts: dict[str, int] = {}
    for item in items:
        counts[item.verdict.value] = counts.get(item.verdict.value, 0) + 1
    summary = _rows(
        *(
            (_VERDICT_LABELS.get(verdict.value, verdict.value), f"{counts[verdict.value]}건")
            for verdict in AffordabilityVerdict
            if counts.get(verdict.value)
        )
    )
    return (
        "<h2>1. 매물별 산출 결과 총괄</h2>"
        "<p class='note'>아래 금액은 표시된 기준시점의 매물 스냅샷과 사용자 재무 "
        "사실로 산출한 계산 결과입니다. 실제 거래 가능 여부와 대출 승인은 포함하지 "
        "않습니다.</p>"
        "<table><caption>가. 매물별 산출 내역</caption>"
        "<thead><tr><th>번호</th><th>매물</th><th>매매가</th><th>총구매비용</th>"
        "<th>필요 대출</th><th>조달 가능액</th><th>부족액</th><th>월 상환액</th>"
        "<th>구매 후 월 잉여</th><th>판정</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<table><caption>나. 판정 분포</caption><tbody>"
        + summary
        + "</tbody></table>"
        "<p class='note'>판정 불가와 판정 대상 아님은 구매할 수 없다는 뜻이 아니라 "
        "이 계산으로 판단하지 못했다는 뜻입니다. 표시된 확인 항목을 채우면 판정이 "
        "달라질 수 있습니다.</p>"
    )


def _narrated_sections(report: FinalReport, start: int) -> tuple[str, tuple[str, ...]]:
    body = ""
    titles: list[str] = []
    outcomes = {item.key: item for item in report.outcomes}
    for offset, section in enumerate(report.form.sections):
        number = start + offset
        # 양식 제목이 "1. 검색 조건…"처럼 자체 번호를 갖고 있어 문서 번호로 바꾼다.
        raw_title = section.title.split(". ", 1)[-1]
        title = f"{number}. {raw_title}"
        titles.append(title)
        body += f"<h2>{escape(title)}</h2><ul class='plain'>"
        for line in section.figures or ("아직 계산하지 않았습니다.",):
            body += f"<li>{escape(str(line).lstrip('- '))}</li>"
        body += "</ul>"

        outcome = outcomes.get(section.key)
        if section.narration:
            body += (
                "<div class='narration'><span class='tag'>[AI 설명 — 기계 검증과 "
                "검증 에이전트를 모두 통과한 문장입니다. 수치와 매물명은 포함하지 "
                "않습니다.]</span>"
                f"{escape(section.narration.strip())}</div>"
            )
        elif outcome is not None and outcome.blocked_by is not None:
            reason = outcome.machine_reason or outcome.judge_reason or ""
            blocked = "기계 검증" if outcome.blocked_by == "machine" else "검증 에이전트"
            body += (
                f"<p class='note'>AI 설명은 {escape(blocked)}에서 채택되지 않아 "
                "싣지 않았습니다"
                + (f" ({escape(reason)})" if reason else "")
                + ". 위 수치는 계산 엔진 산출값이므로 그대로 유효합니다.</p>"
            )
    return body, tuple(titles)


def _attachment_sources(payload: PropertyReportAIInput) -> str:
    sources = list(dict.fromkeys(payload.policy_sources))
    rows = "".join(f"<li>{escape(str(item))}</li>" for item in sources)
    license_note = payload.handoff.source.license_note
    return (
        "<section class='attach'><h2>붙임 1. 적용 규제·정책 근거</h2>"
        + (f"<ul class='plain'>{rows}</ul>" if rows else "<p>기록된 정책 출처가 없습니다.</p>")
        + (
            f"<h3>가. 매물 데이터 이용조건</h3><p>{escape(license_note)}</p>"
            if license_note
            else ""
        )
        + "<p class='note'>각 규제 상수는 시행일과 출처를 함께 관리하며, 산출 "
        "기준일에 유효한 값만 사용했습니다.</p></section>"
    )


def _attachment_missing(payload: PropertyReportAIInput) -> str:
    rows = "".join(f"<li>{escape(str(item))}</li>" for item in payload.missing_inputs)
    diagnosis = payload.financial_diagnosis
    not_run = (
        "<p class='note'>현금흐름 진단을 실행하지 않아 2항의 수치가 비어 있습니다.</p>"
        if diagnosis.run_status is not SectionRunStatus.COMPLETED
        else ""
    )
    return (
        "<section class='attach'><h2>붙임 2. 확인되지 않은 항목</h2>"
        "<p class='note'>아래 항목은 값이 없어 계산에 사용하지 않았습니다. "
        "<strong>확인되지 않음은 0이나 해당 없음이 아니며</strong>, 확인하면 "
        "결과가 달라질 수 있습니다.</p>"
        + (f"<ul class='plain'>{rows}</ul>" if rows else "<p>없습니다.</p>")
        + not_run
        + "</section>"
    )


def _closing(report: FinalReport) -> str:
    items = "".join(f"<li>{escape(item)}</li>" for item in report.form.disclaimers)
    models = []
    if report.writer_model:
        models.append(f"설명 작성 {escape(report.writer_model)}")
    if report.judge_model:
        models.append(f"설명 검증 {escape(report.judge_model)}")
    model_line = (
        f"<p class='note'>문장 설명 생성에 사용한 모델: {' / '.join(models)}.</p>"
        if models
        else ""
    )
    return (
        f"<div class='disclaimer'><h3>유의사항</h3><ul class='plain'>{items}</ul>"
        + model_line
        + "<p class='note'>이 문서는 금융기관의 대출 승인 통지도, 매물 거래를 "
        "중개하거나 보증하는 문서도 아닙니다. 매물의 실제 상태와 권리관계는 "
        "등기부와 현장 확인으로, 대출 가능 여부와 적용 금리는 취급 금융기관의 "
        "심사로 결정됩니다.</p></div>"
        "<p class='issuer'>주택구매 금융 라이프 컨설팅 서비스 (계산 엔진 산출)</p>"
    )


def render_property_official_report(
    report: FinalReport,
    payload: PropertyReportAIInput,
) -> str:
    """매물 보고서의 인쇄용 정식 문서 HTML을 만든다."""

    narrated, titles = _narrated_sections(report, start=2)
    return (
        # 완전한 문서로 낸다. 정상 사용법이 파일로 저장해 인쇄하는 것이라
        # 문서 자체에 charset이 없으면 한글이 깨진다.
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>매물별 구매 가능성 산출 결과 보고서</title>"
        f"<style>{PRINT_STYLE}</style></head><body>"
        "<h1>매물별 구매 가능성 산출 결과 보고서</h1>"
        f"<p class='subtitle'>산출 기준일 {escape(payload.as_of.isoformat())} · "
        "본 문서는 계산 결과이며 대출 승인이나 거래 성사를 의미하지 않습니다</p>"
        + _masthead(payload)
        + _toc(titles)
        + _overview(payload)
        + narrated
        + _attachment_sources(payload)
        + _attachment_missing(payload)
        + _closing(report)
        + "</body></html>"
    )


__all__ = ["render_property_official_report"]
