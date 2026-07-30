"""최종 보고서를 사용자 화면용 HTML 대시보드로 만든다.

목적:
    "어떤 상품이 되고 왜 안 되는지"가 맨 위에서 한눈에 읽히게 한다.
기능:
    계산 결과의 수치를 막대·누적막대·불릿·상태 셀로 그리고, 검증을 통과한 AI
    서술을 그 아래에 붙인다. 수치 줄과 AI 서술은 시각적으로 구분한다.
근거:
    - SSOT §20의 "AI가 계산값을 바꾸지 않는다"는 보증은 사용자에게도 보여야
      의미가 있다. 어느 것이 엔진 산출이고 어느 것이 AI 서술인지 구분되지 않으면
      보증했다는 사실을 확인할 수 없다.
    - 상태는 색만으로 표시하지 않는다. 아이콘과 텍스트 라벨을 항상 함께 둔다 —
      상태색 `#fab219`는 흰 배경에서 1.83:1이라 색 단독으로는 읽히지 않는다.
    - 금액은 원 단위 정수로 내린다. 이분탐색 결과의 소수점을 사용자에게 보이면
      안 된다(단위 규약).

우대조건은 왜 인자로 받는가:
    `spcl_cnd`(우대금리 요건)·`erly_rpay_fee`·`loan_inci_expn`은 원천 상품
    데이터에만 있고 ``ReportAIInput``에는 없다. 표시 전용이므로 여기서 인자로
    받아 그리고, **AI에는 보내지 않는다** — 외부로 나가는 데이터가 늘어날 이유가
    없고, 자유텍스트 자격조건은 자동 판정 대상도 아니다(부록 B-3).
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from html import escape

from app.reports.ai_explanation.pipeline import FinalReport
from app.schemas.simulation import SimulationResult

# (facts 키, 라벨, 상태 톤, 아이콘). 상태 톤은 dataviz 고정 상태 팔레트에 대응한다.
_STATES: tuple[tuple[str, str, str, str], ...] = (
    ("executable", "실행 가능", "good", "✓"),
    ("not_executable", "최소금액 미달", "serious", "▽"),
    ("unresolved", "입력 부족", "warning", "?"),
    ("rejected", "자격 미달", "critical", "✕"),
)

# 표시 전용 상품 조건. 키는 원천 데이터의 필드명이다.
TERM_LABELS: tuple[tuple[str, str], ...] = (
    ("spcl_cnd", "우대 조건"),
    ("erly_rpay_fee", "중도상환수수료"),
    ("loan_inci_expn", "부대비용"),
)

_STYLE = """
:root{color-scheme:light;
--plane:#f6f7fb;--card:#fff;--ink:#0f172a;--ink-2:#495467;--ink-3:#6b7689;
--rule:#e1e0d9;--base:#c3c2b7;--eq:#2a78d6;--loan:#1baf7a;--violet:#4a3aa7;
--gap:#c3c2b7;--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
--plane:#0d0d0d;--card:#161b25;--ink:#e8ebf2;--ink-2:#a8b1c4;--ink-3:#8b95a9;
--rule:#2c2c2a;--base:#383835;--eq:#3987e5;--loan:#199e70;--violet:#9085e9;--gap:#383835;}}
:root[data-theme="dark"]{color-scheme:dark;
--plane:#0d0d0d;--card:#161b25;--ink:#e8ebf2;--ink-2:#a8b1c4;--ink-3:#8b95a9;
--rule:#2c2c2a;--base:#383835;--eq:#3987e5;--loan:#199e70;--violet:#9085e9;--gap:#383835;}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);font-size:15.5px;line-height:1.68;
font-family:"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:54rem;margin:0 auto;padding:2.75rem 1.25rem 4rem;display:flex;
flex-direction:column;gap:1.15rem}
.head{display:flex;flex-direction:column;gap:.7rem;padding-bottom:1.1rem;
border-bottom:2px solid var(--rule)}
.eyebrow{margin:0;font-size:.71rem;font-weight:650;letter-spacing:.14em;
text-transform:uppercase;color:var(--ink-3)}
h1{margin:0;font-size:1.8rem;line-height:1.22;font-weight:690;letter-spacing:-.02em;
text-wrap:balance}
.facts{margin:.1rem 0 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));
gap:.3rem 1.2rem;font-size:.9rem}
.facts dt{color:var(--ink-3);font-size:.78rem}
.facts dd{margin:0;font-weight:620;font-variant-numeric:tabular-nums}
.headline{margin:0;font-size:.95rem;color:var(--ink-2)}
.headline strong{color:var(--ink);font-variant-numeric:tabular-nums}
.headline em{font-style:normal;font-weight:620;color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(8.5rem,1fr));gap:.7rem}
.tile{background:var(--card);border:1px solid var(--rule);border-top:3px solid var(--base);
border-radius:10px;padding:.85rem .9rem;display:grid;grid-template-columns:auto 1fr;
gap:0 .55rem;align-items:center}
.tile-icon{grid-row:span 2;width:1.7rem;height:1.7rem;border-radius:50%;display:grid;
place-items:center;font-size:.85rem;font-weight:700;color:#fff}
.tile-num{font-size:1.5rem;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.tile-label{font-size:.8rem;color:var(--ink-2)}
.tile-sub{font-size:.72rem;color:var(--ink-3)}
.tile.good{border-top-color:var(--good)}.tile.good .tile-icon{background:var(--good)}
.tile.serious{border-top-color:var(--serious)}.tile.serious .tile-icon{background:var(--serious)}
.tile.warning{border-top-color:var(--warning)}
.tile.warning .tile-icon{background:var(--warning);color:#3a2a00}
.tile.critical{border-top-color:var(--critical)}
.tile.critical .tile-icon{background:var(--critical)}
.card{background:var(--card);border:1px solid var(--rule);border-radius:12px;
padding:1.25rem 1.35rem;display:flex;flex-direction:column;gap:.8rem}
h2{margin:0;font-size:1.02rem;font-weight:660;display:flex;align-items:center;gap:.5rem}
.dot{width:.55rem;height:.55rem;border-radius:50%;flex:none}
.dot.good{background:var(--good)}.dot.crit{background:var(--critical)}
.dot.blue{background:var(--eq)}
.lede{margin:-.25rem 0 0;font-size:.88rem;color:var(--ink-2)}
.note{margin:0;font-size:.82rem;color:var(--ink-3)}
.bars{position:relative;display:flex;flex-direction:column;gap:.85rem;padding-top:1.35rem}
.ref{position:absolute;top:1rem;bottom:0;border-left:2px dashed var(--ink-3);pointer-events:none}
.ref span{position:absolute;top:-1.15rem;left:.3rem;font-size:.72rem;font-weight:620;
color:var(--ink-2);white-space:nowrap;font-variant-numeric:tabular-nums}
.ref.flip span{left:auto;right:.3rem}
.bar-row{display:flex;flex-direction:column;gap:.12rem}
.bar-head{display:flex;align-items:baseline;gap:.45rem;flex-wrap:wrap}
.bar-head strong{font-size:.88rem;font-weight:620}
.bar-opt{font-size:.75rem;color:var(--ink-3);overflow-wrap:anywhere}
.bar-rate{margin-left:auto;font-size:.8rem;font-weight:620;color:var(--ink-2);
font-variant-numeric:tabular-nums;white-space:nowrap}
.bar-track{position:relative;height:1.35rem;display:flex;align-items:center}
.bar-fill{height:1rem;background:var(--loan);border-radius:0 4px 4px 0;min-width:2px}
.bar-fill.short{opacity:.62}
.bar-value{margin-left:.5rem;font-size:.82rem;font-weight:620;white-space:nowrap;
font-variant-numeric:tabular-nums}
.callout{margin:.2rem 0 0;padding:.65rem .85rem;border-radius:7px;font-size:.88rem;
display:flex;gap:.5rem}
.callout.warn{background:color-mix(in srgb,var(--warning) 16%,transparent);
border-left:3px solid var(--warning)}
.terms{border-top:1px solid var(--rule);padding-top:.7rem;display:flex;flex-direction:column;
gap:.35rem}
.terms.first{border-top:0;padding-top:0}
.terms-name{margin:0;font-size:.88rem;font-weight:650}
.term{display:grid;grid-template-columns:6.5rem 1fr;gap:.5rem;font-size:.82rem}
.term-label{color:var(--ink-3)}
.term-body{color:var(--ink-2);white-space:pre-line;overflow-wrap:anywhere}
.grid{width:100%;border-collapse:collapse;font-size:.85rem;display:block;overflow-x:auto}
.grid thead th{text-align:left;font-size:.74rem;letter-spacing:.06em;text-transform:uppercase;
color:var(--ink-3);font-weight:650;padding:0 .6rem .45rem 0;border-bottom:1px solid var(--rule)}
.grid td{padding:.6rem .6rem .6rem 0;border-bottom:1px solid var(--rule);vertical-align:top}
.grid tbody tr:last-child td{border-bottom:0}
.cell-name{min-width:11rem}
.cell-name strong{display:block;font-weight:620;overflow-wrap:anywhere}
.reasons{margin:0;padding-left:1rem;display:flex;flex-direction:column;gap:.2rem;color:var(--ink-2)}
.chip{display:inline-flex;align-items:center;gap:.3rem;padding:.16rem .5rem;border-radius:999px;
font-size:.76rem;font-weight:620;white-space:nowrap;color:var(--ink)}
.chip.warning{background:color-mix(in srgb,var(--warning) 22%,transparent)}
.chip.critical{background:color-mix(in srgb,var(--critical) 18%,transparent)}
.chip.serious{background:color-mix(in srgb,var(--serious) 20%,transparent)}
.chip.good{background:color-mix(in srgb,var(--good) 16%,transparent)}
.stack{display:flex;height:2.1rem;border-radius:5px;overflow:hidden;gap:2px;background:var(--card)}
.seg{min-width:3px}.seg.eq{background:var(--eq)}.seg.loan{background:var(--loan)}
.seg.gap{background:var(--gap)}
.legend{margin:0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;
font-size:.84rem;color:var(--ink-2)}
.legend strong{color:var(--ink);font-variant-numeric:tabular-nums}
.swatch{display:inline-block;width:.7rem;height:.7rem;border-radius:2px;margin-right:.35rem;
vertical-align:-1px}
.swatch.eq{background:var(--eq)}.swatch.loan{background:var(--loan)}
.swatch.gap{background:var(--gap)}.swatch.crit{background:var(--critical)}
.bullet{padding:1.3rem 0 .3rem}
.bullet-track{position:relative;height:1.5rem;border-radius:4px;
background:color-mix(in srgb,var(--base) 28%,transparent)}
.bullet-worst{position:absolute;inset:0 auto 0 0;height:100%;border-radius:4px 0 0 4px;
background:color-mix(in srgb,var(--critical) 45%,transparent)}
.bullet-fill{position:absolute;inset:0 auto 0 0;height:100%;background:var(--loan);
border-radius:4px 0 0 4px;z-index:1}
.bullet-thresh{position:absolute;top:-1.15rem;bottom:-.3rem;border-left:2px solid var(--ink);
z-index:2}
.bullet-thresh span{position:absolute;top:-.1rem;left:.3rem;font-size:.74rem;font-weight:620;
white-space:nowrap;font-variant-numeric:tabular-nums}
.cells{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));gap:.5rem}
.cell{border:1px solid var(--rule);border-left-width:3px;border-radius:7px;padding:.55rem .7rem;
display:flex;flex-direction:column;gap:.1rem}
.cell-icon{font-size:.8rem;font-weight:700}
.cell-title{font-size:.8rem;font-weight:600;overflow-wrap:anywhere}
.cell-status{font-size:.72rem;color:var(--ink-3);letter-spacing:.06em}
.cell.good{border-left-color:var(--good)}.cell.good .cell-icon{color:var(--good)}
.cell.critical{border-left-color:var(--critical);
background:color-mix(in srgb,var(--critical) 8%,transparent)}
.cell.critical .cell-icon{color:var(--critical)}
.cell.warning{border-left-color:var(--warning)}
.rate-row{display:grid;grid-template-columns:minmax(9rem,13rem) 1fr;gap:.3rem .9rem;
align-items:center}
.rate-label{display:flex;flex-direction:column;font-size:.88rem;font-weight:620}
.rate-label span{font-size:.74rem;font-weight:400;color:var(--ink-3)}
.rate-track{position:relative;height:1.5rem;display:flex;align-items:center}
.rate-fill{height:.9rem;border-radius:0 4px 4px 0;min-width:2px}
.rate-fill.loan{background:var(--loan)}.rate-fill.violet{background:var(--violet)}
.rate-value{margin-left:.5rem;font-size:.82rem;font-weight:620;font-variant-numeric:tabular-nums}
.ai{border-left:3px solid var(--eq);border-radius:0 7px 7px 0;padding:.7rem .9rem;
background:color-mix(in srgb,var(--eq) 8%,transparent);display:flex;flex-direction:column;gap:.2rem}
.ai-title{margin:0;font-size:.74rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
color:var(--eq)}
.ai p:last-child{margin:0;font-size:.9rem}
.blocked{border-left:3px solid var(--warning);border-radius:0 7px 7px 0;padding:.7rem .9rem;
background:color-mix(in srgb,var(--warning) 12%,transparent);display:flex;flex-direction:column;
gap:.2rem}
.blocked .ai-title{color:var(--ink-2)}
footer{border-top:1px solid var(--rule);padding-top:1.1rem;display:flex;flex-direction:column;
gap:.35rem}
.tag{margin:.4rem 0 0;font-size:.71rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
color:var(--ink-3)}
footer ul{margin:0;padding-left:1.1rem;font-size:.82rem;color:var(--ink-2);display:flex;
flex-direction:column;gap:.25rem;word-break:break-word}
.provenance{margin:.6rem 0 0;font-size:.78rem;color:var(--ink-3)}
:focus-visible{outline:2px solid var(--eq);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:40rem){.wrap{padding:2rem 1rem 3rem}h1{font-size:1.45rem}
.rate-row{grid-template-columns:1fr}.term{grid-template-columns:1fr;gap:.1rem}
.facts{grid-template-columns:1fr}}
"""


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _won(value: object) -> str:
    parsed = _decimal(value)
    return f"{int(parsed):,}원" if parsed is not None else str(value)


def _pct(value: object) -> str:
    parsed = _decimal(value)
    return f"{parsed * 100:.2f}%" if parsed is not None else str(value)


def _facts(simulation: SimulationResult, name: str) -> dict[str, object]:
    """구간의 원본 결과. ``SimulationResult``를 읽는 이유는 4갈래 분류
    (``executable``/``not_executable``/``unresolved``/``rejected``)가 여기에만 있고
    ``ReportAIInput``에는 종합추천 수준 요약만 담기기 때문이다. 화면은 전부 보여줘야
    "왜 이 상품이 빠졌는가"에 답할 수 있다."""
    section = getattr(simulation, name)
    return dict(section.result) if section.result else {}


def _option_label(record: Mapping[str, object]) -> str:
    option = record.get("option")
    if not isinstance(option, Mapping):
        return "기본 옵션"
    bits = (
        option.get("mortgage_type_name"),
        option.get("repayment_type_name"),
        option.get("rate_type_name"),
    )
    return " · ".join(str(b) for b in bits if b) or "기본 옵션"


def _records(loan: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = loan.get(key)
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def render_report_html(
    report: FinalReport,
    simulation: SimulationResult,
    *,
    product_terms: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """판정 결과를 상단에 두고 나머지를 도표로 그린 보고서 페이지."""
    loan = _facts(simulation, "loan_simulation")
    stress = _facts(simulation, "stress_test")
    savings = _facts(simulation, "savings_portfolio")
    recommendation = _facts(simulation, "recommendation")
    rec_loan = recommendation.get("loan") if isinstance(recommendation.get("loan"), Mapping) else {}
    assert isinstance(rec_loan, Mapping)
    primary = rec_loan.get("primary") if isinstance(rec_loan.get("primary"), Mapping) else {}
    assert isinstance(primary, Mapping)

    goal = simulation.goal
    required = _decimal(rec_loan.get("required_amount")) or Decimal(0)
    equity = _decimal(simulation.user_summary.liquid_assets) or Decimal(0)
    target = _decimal(goal.target_amount) or Decimal(0)

    out: list[str] = ['<header class="head">']
    out.append('<p class="eyebrow">대출 상품 판정</p>')
    out.append("<h1>어떤 대출이 되고, 왜 안 되는가</h1>")
    out.append('<dl class="facts">')
    out.append(f"<dt>기준일</dt><dd>{escape(simulation.as_of.isoformat())}</dd>")
    out.append(f"<dt>목표</dt><dd>{escape(_won(target))}</dd>")
    if required > 0:
        out.append(f"<dt>필요 대출금액</dt><dd>{escape(_won(required))}</dd>")
    if goal.region_code:
        out.append(f"<dt>지역코드</dt><dd>{escape(goal.region_code)}</dd>")
    out.append(f"<dt>목표일</dt><dd>{escape(goal.target_date.isoformat())}</dd>")
    out.append("</dl></header>")

    # ── 판정 요약 ─────────────────────────────────────────────────────────────
    option_counts = {key: len(_records(loan, key)) for key, *_ in _STATES}
    product_counts = {
        key: len({str(item.get("product_name")) for item in _records(loan, key)})
        for key, *_ in _STATES
    }
    total_products = len(
        {
            str(item.get("product_name"))
            for key, *_ in _STATES
            for item in _records(loan, key)
        }
    )
    if total_products:
        out.append(
            f'<p class="headline">상품 <strong>{total_products}건</strong> 중 '
            f'<strong>{product_counts["executable"]}건</strong>만 실행 가능합니다. '
            "아래 숫자는 <em>금리·상환방식 옵션</em> 단위입니다.</p>"
        )
        out.append('<section class="tiles" aria-label="옵션 판정 요약">')
        for key, label, tone, icon in _STATES:
            out.append(
                f'<div class="tile {tone}"><span class="tile-icon" aria-hidden="true">{icon}</span>'
                f'<span class="tile-num">{option_counts[key]}</span>'
                f'<span class="tile-label">{escape(label)}<br>'
                f'<span class="tile-sub">상품 {product_counts[key]}건</span></span></div>'
            )
        out.append("</section>")
    else:
        section = simulation.loan_simulation
        out.append('<section class="card"><h2>대출 계산이 실행되지 않았습니다</h2>')
        if section.missing_inputs:
            out.append(
                '<p class="lede">확인이 필요한 입력: '
                + escape(", ".join(section.missing_inputs))
                + "</p>"
            )
        out.append("<ul class='reasons'>")
        out.extend(f"<li>{escape(reason)}</li>" for reason in section.reasons)
        out.append("</ul></section>")

    # ── 실행 가능한 옵션 ───────────────────────────────────────────────────────
    executable = _records(loan, "executable")
    if executable:
        amounts = [(_decimal(r.get("amount")) or Decimal(0), r) for r in executable]
        best = max(amount for amount, _ in amounts)
        axis = max(best, required, Decimal(1))
        out.append('<section class="card">')
        out.append('<h2><span class="dot good" aria-hidden="true"></span>실행 가능한 옵션</h2>')
        out.append(
            '<p class="lede">막대는 계산된 대출 가능액입니다.'
            + (f" 점선은 필요 대출금액 {escape(_won(required))}입니다." if required > 0 else "")
            + "</p>"
        )
        out.append('<div class="bars">')
        if required > 0:
            ratio = float(required / axis * 100)
            flip = " flip" if ratio > 70 else ""
            out.append(
                f'<div class="ref{flip}" style="left:{ratio:.2f}%">'
                f"<span>필요 {escape(_won(required))}</span></div>"
            )
        for amount, record in sorted(amounts, key=lambda pair: pair[0], reverse=True):
            width = float(amount / axis * 100)
            short = "" if required > 0 and amount >= required else " short"
            name = str(record.get("product_name"))
            out.append('<div class="bar-row"><div class="bar-head">')
            out.append(f"<strong>{escape(name)}</strong>")
            out.append(f'<span class="bar-opt">{escape(_option_label(record))}</span>')
            rate = record.get("annual_rate")
            if rate is not None:
                out.append(f'<span class="bar-rate">연 {escape(_pct(rate))}</span>')
            out.append("</div>")
            out.append(
                f'<div class="bar-track" title="{escape(name)} — {escape(_won(amount))}">'
                f'<div class="bar-fill{short}" style="width:{width:.2f}%"></div>'
                f'<span class="bar-value">{escape(_won(amount))}</span></div></div>'
            )
        out.append("</div>")
        shortfall = max(required - best, Decimal(0))
        if shortfall > 0:
            out.append(
                '<p class="callout warn"><span aria-hidden="true">▲</span>'
                "가장 큰 한도를 써도 <strong>필요 대출금액 대비 "
                f"{escape(_won(shortfall))}</strong>이 부족합니다.</p>"
            )
        out.append("</section>")

        # ── 우대조건 원문 ──────────────────────────────────────────────────────
        if product_terms:
            shown: list[str] = []
            blocks: list[str] = []
            for _amount, record in amounts:
                name = str(record.get("product_name"))
                if name in shown:
                    continue
                terms = product_terms.get(name)
                if not terms:
                    continue
                shown.append(name)
                rows = [
                    f'<div class="term"><span class="term-label">{escape(label)}</span>'
                    f'<span class="term-body">{escape(str(terms[field]).strip())}</span></div>'
                    for field, label in TERM_LABELS
                    if terms.get(field)
                ]
                if rows:
                    css = "terms first" if not blocks else "terms"
                    blocks.append(
                        f'<div class="{css}"><p class="terms-name">{escape(name)}</p>'
                        + "".join(rows)
                        + "</div>"
                    )
            if blocks:
                out.append('<section class="card">')
                out.append(
                    '<h2><span class="dot blue" aria-hidden="true"></span>'
                    "우대금리 · 부대비용 조건</h2>"
                )
                out.append(
                    '<p class="lede">원천 상품 데이터의 <strong>원문</strong>입니다. '
                    "자유텍스트 조건은 자동 판정하지 않으므로 달성 여부는 상품 설명서에서 "
                    "직접 확인해야 합니다.</p>"
                )
                out.extend(blocks)
                out.append("</section>")

    # ── 제외된 옵션 ───────────────────────────────────────────────────────────
    blocked = [
        (label, tone, icon, record)
        for key, label, tone, icon in _STATES
        if key != "executable"
        for record in _records(loan, key)
    ]
    if blocked:
        out.append('<section class="card">')
        out.append('<h2><span class="dot crit" aria-hidden="true"></span>제외된 옵션과 사유</h2>')
        out.append(
            '<p class="lede">입력 부족(?)과 자격 미달(✕)은 다릅니다. '
            "앞은 알려주면 계산되고, 뒤는 조건 자체가 맞지 않습니다.</p>"
        )
        out.append('<table class="grid"><thead><tr>')
        out.append("<th>판정</th><th>상품</th><th>사유</th>")
        out.append("</tr></thead><tbody>")
        for label, tone, icon, record in blocked:
            out.append("<tr>")
            out.append(
                f'<td><span class="chip {tone}"><span aria-hidden="true">{icon}</span>'
                f"{escape(label)}</span></td>"
            )
            out.append(
                f'<td class="cell-name"><strong>{escape(str(record.get("product_name")))}</strong>'
                f'<span class="bar-opt">{escape(_option_label(record))}</span></td>'
            )
            reasons = record.get("reasons")
            items = [str(r) for r in reasons] if isinstance(reasons, list) else []
            if not items:
                missing = record.get("missing_inputs")
                if isinstance(missing, list) and missing:
                    items = ["확인이 필요한 입력: " + ", ".join(str(m) for m in missing)]
            out.append('<td><ul class="reasons">')
            out.extend(f"<li>{escape(item)}</li>" for item in items[:3] or ["사유 없음"])
            out.append("</ul></td></tr>")
        out.append("</tbody></table></section>")

    # ── 자금 조달 구성 ─────────────────────────────────────────────────────────
    if executable and target > 0:
        best = max((_decimal(r.get("amount")) or Decimal(0)) for r in executable)
        segments = [
            ("자기자본", equity, "eq"),
            ("대출 가능액", best, "loan"),
            ("부족", max(target - equity - best, Decimal(0)), "gap"),
        ]
        out.append('<section class="card">')
        out.append('<h2><span class="dot blue" aria-hidden="true"></span>자금 조달 구성</h2>')
        out.append('<div class="stack" role="img" aria-label="자금 조달 구성">')
        for label, value, css in segments:
            if value > 0:
                out.append(
                    f'<div class="seg {css}" style="flex:{float(value):.0f}" '
                    f'title="{escape(label)} {escape(_won(value))}"></div>'
                )
        out.append('</div><ul class="legend">')
        for label, value, css in segments:
            if value > 0:
                out.append(
                    f'<li><span class="swatch {css}" aria-hidden="true"></span>'
                    f"{escape(label)} <strong>{escape(_won(value))}</strong></li>"
                )
        out.append("</ul>")
        out.append(f'<p class="note">합계 {escape(_won(target))} (목표 금액)</p></section>')

    # ── DSR ───────────────────────────────────────────────────────────────────
    base_dsr = _decimal(primary.get("expected_dsr"))
    worst_dsr = _decimal(stress.get("maximum_dsr"))
    scenarios = _records(stress, "scenarios")
    safe_dsr = _decimal(scenarios[0].get("safe_dsr")) if scenarios else None
    if base_dsr is not None or worst_dsr is not None:
        known = [v for v in (base_dsr, worst_dsr, safe_dsr) if v is not None]
        # 축을 최댓값보다 15% 넓게 잡아 임계선 라벨이 오른쪽 끝에서 잘리지 않게 한다.
        scale = max(known + [Decimal("0.01")]) * Decimal("1.15")
        out.append('<section class="card">')
        out.append(
            '<h2><span class="dot blue" aria-hidden="true"></span>'
            "DSR — 기본 조건과 최악 시나리오</h2>"
        )
        out.append('<div class="bullet"><div class="bullet-track">')
        if worst_dsr is not None:
            width = float(worst_dsr / scale * 100)
            out.append(f'<div class="bullet-worst" style="width:{width:.2f}%"></div>')
        if base_dsr is not None:
            width = float(base_dsr / scale * 100)
            out.append(f'<div class="bullet-fill" style="width:{width:.2f}%"></div>')
        if safe_dsr is not None:
            out.append(
                f'<div class="bullet-thresh" style="left:{float(safe_dsr/scale*100):.2f}%">'
                f"<span>안전기준 {escape(_pct(safe_dsr))}</span></div>"
            )
        out.append('</div></div><ul class="legend">')
        if base_dsr is not None:
            out.append(
                '<li><span class="swatch loan" aria-hidden="true"></span>기본 조건 '
                f"<strong>{escape(_pct(base_dsr))}</strong></li>"
            )
        if worst_dsr is not None:
            exceeded = safe_dsr is not None and worst_dsr > safe_dsr
            out.append(
                '<li><span class="swatch crit" aria-hidden="true"></span>최악 시나리오 '
                f"<strong>{escape(_pct(worst_dsr))}</strong>"
                + (" · 기준 초과" if exceeded else "")
                + "</li>"
            )
        out.append("</ul></section>")

    # ── 스트레스 시나리오 ──────────────────────────────────────────────────────
    if scenarios:
        out.append('<section class="card">')
        out.append(
            '<h2><span class="dot good" aria-hidden="true"></span>생활 스트레스 시나리오</h2>'
        )
        out.append(
            '<p class="lede">규제 심사가 아니라 생활 안정성 점검입니다. '
            f'{stress.get("pass_count", 0)}개 통과 · {stress.get("fail_count", 0)}개 실패 · '
            f'{stress.get("unknown_count", 0)}개 미확정.</p>'
        )
        out.append('<div class="cells">')
        for item in scenarios:
            scenario = item.get("scenario")
            name = str(scenario.get("name")) if isinstance(scenario, Mapping) else "시나리오"
            status = str(item.get("status"))
            tone = {"PASS": "good", "FAIL": "critical"}.get(status, "warning")
            icon = {"PASS": "✓", "FAIL": "✕"}.get(status, "?")
            payment = item.get("monthly_payment")
            tip = f"{name} — 월 상환액 {_won(payment)}" if payment is not None else name
            out.append(
                f'<div class="cell {tone}" title="{escape(tip)}">'
                f'<span class="cell-icon" aria-hidden="true">{icon}</span>'
                f'<span class="cell-title">{escape(name)}</span>'
                f'<span class="cell-status">{escape(status)}</span></div>'
            )
        out.append("</div></section>")

    # ── 금리 ──────────────────────────────────────────────────────────────────
    actual = _decimal(primary.get("annual_rate"))
    assessed = _decimal(primary.get("assessment_annual_rate"))
    if actual is not None:
        scale = max([v for v in (actual, assessed) if v is not None])
        out.append('<section class="card">')
        out.append(
            '<h2><span class="dot blue" aria-hidden="true"></span>실제 금리와 심사용 금리</h2>'
        )
        pairs = [("실제 적용 금리", actual, "loan", "상환액 계산에 쓰입니다")]
        if assessed is not None:
            pairs.append(
                (
                    "심사용 금리",
                    assessed,
                    "violet",
                    "한도 산정에만 쓰이며 실제로 내는 금리가 아닙니다",
                )
            )
        for label, value, css, note in pairs:
            out.append('<div class="rate-row">')
            out.append(f'<div class="rate-label">{escape(label)}<span>{escape(note)}</span></div>')
            out.append(
                f'<div class="rate-track" title="{escape(label)} 연 {escape(_pct(value))}">'
                f'<div class="rate-fill {css}" style="width:{float(value/scale*100):.2f}%"></div>'
                f'<span class="rate-value">연 {escape(_pct(value))}</span></div></div>'
            )
        out.append("</section>")

    # ── 예·적금 ───────────────────────────────────────────────────────────────
    allocations = _records(savings, "allocations")
    if allocations:
        out.append('<section class="card">')
        out.append('<h2><span class="dot blue" aria-hidden="true"></span>예·적금 배분</h2>')
        out.append('<table class="grid"><thead><tr><th>상품</th><th>배분</th>'
                   "<th>예상 만기</th></tr></thead><tbody>")
        for item in allocations:
            out.append(
                f'<tr><td class="cell-name"><strong>'
                f'{escape(str(item.get("product_name")))}</strong></td>'
                f"<td>{escape(_won(item.get('allocation_amount')))}</td>"
                f"<td>{escape(_won(item.get('expected_maturity_amount')))}</td></tr>"
            )
        out.append("</tbody></table></section>")

    # ── AI 설명 ───────────────────────────────────────────────────────────────
    outcomes = {item.key: item for item in report.outcomes}
    out.append('<section class="card">')
    out.append('<h2><span class="dot blue" aria-hidden="true"></span>AI 설명</h2>')
    verdict = (
        "모든 절이 기계 검증과 검증 에이전트를 통과했습니다."
        if report.fully_verified
        else f"{len(report.adopted_sections)}개 절 통과 · "
        f"{len(report.figures_only_sections)}개 절 미채택"
    )
    out.append(
        f'<p class="lede">{escape(verdict)} '
        "서술에는 수치를 쓸 수 없습니다 — 수치는 위 도표가 보여줍니다.</p>"
    )
    for section in report.form.sections:
        _, _, title = section.title.partition(". ")
        if section.narration:
            out.append(
                f'<div class="ai"><p class="ai-title">{escape(title)}</p>'
                f"<p>{escape(section.narration)}</p></div>"
            )
            continue
        outcome = outcomes.get(section.key)
        if outcome is None:
            continue
        reason = outcome.machine_reason or outcome.judge_reason or "사유 없음"
        out.append(
            f'<div class="blocked"><p class="ai-title">{escape(title)} · 미채택</p>'
            f"<p>{escape(reason)}</p>"
            '<p class="note">위 수치는 계산 엔진 산출값이므로 그대로 유효합니다.</p></div>'
        )
    out.append("</section>")

    # ── 출처 ──────────────────────────────────────────────────────────────────
    out.append("<footer>")
    if report.form.policy_sources:
        out.append('<p class="tag">근거 출처</p><ul>')
        out.extend(f"<li>{escape(source)}</li>" for source in report.form.policy_sources)
        out.append("</ul>")
    out.append('<p class="tag">유의사항</p><ul>')
    out.extend(f"<li>{escape(note)}</li>" for note in report.form.disclaimers)
    out.append("</ul>")
    models = " · ".join(
        part
        for part in (
            f"작성 모델 {report.writer_model}" if report.writer_model else "",
            f"판정 모델 {report.judge_model}" if report.judge_model else "",
        )
        if part
    )
    if models:
        out.append(f'<p class="provenance">{escape(models)}</p>')
    out.append("</footer>")

    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>대출 상품 판정 보고서</title><style>{_STYLE}</style></head>"
        f'<body><main class="wrap">{"".join(out)}</main></body></html>'
    )


def collect_product_terms(
    candidates: object,
) -> dict[str, dict[str, str]]:
    """상품 후보에서 표시 전용 조건 원문을 뽑는다.

    계산에 쓰지 않고 화면에만 쓴다. AI에도 보내지 않는다.
    """
    terms: dict[str, dict[str, str]] = {}
    if not isinstance(candidates, (list, tuple)):
        return terms
    for candidate in candidates:
        name = getattr(candidate, "product_name", None)
        base = getattr(candidate, "base_data", None)
        if not name or not isinstance(base, Mapping):
            continue
        picked = {
            field: str(base[field]).strip()
            for field, _label in TERM_LABELS
            if base.get(field)
        }
        if picked:
            terms[str(name)] = picked
    return terms


__all__ = ["TERM_LABELS", "collect_product_terms", "render_report_html"]
