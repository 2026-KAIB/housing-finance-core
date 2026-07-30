"""최종 보고서를 사용자 화면용 HTML로 만든다.

목적:
    프론트엔드가 붙기 전에도 보고서를 눈으로 확인할 수 있게 한다.
기능:
    수치 줄과 AI 서술을 **시각적으로 구분**해 렌더링하고, 두 에이전트를 통과하지
    못한 절에는 그 사유를 표시한다.
근거:
    SSOT §20의 "AI가 계산값을 바꾸지 않는다"는 보증은 사용자에게도 보여야 의미가
    있다. 어느 문장이 엔진 산출이고 어느 문장이 AI 서술인지 구분되지 않으면
    보증했다는 사실을 확인할 수 없다.
"""

from html import escape

from app.reports.ai_explanation.pipeline import FinalReport
from app.reports.ai_explanation.verifier_agent import Verdict

_STYLE = """\
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem; line-height: 1.7;
  font-family: system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
  background: Canvas; color: CanvasText;
}
main { max-width: 46rem; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .5rem; padding-bottom: .3rem;
     border-bottom: 1px solid color-mix(in srgb, CanvasText 20%, transparent); }
.meta { color: color-mix(in srgb, CanvasText 65%, transparent); font-size: .9rem; }
.figures { margin: 0; padding: .75rem 1rem .75rem 2rem;
  background: color-mix(in srgb, CanvasText 5%, transparent);
  border-left: 3px solid color-mix(in srgb, CanvasText 35%, transparent);
  border-radius: 4px; }
.figures li { margin: .15rem 0; }
.narration { margin: .75rem 0 0; padding: .75rem 1rem;
  border-left: 3px solid #4f7cff; border-radius: 4px;
  background: color-mix(in srgb, #4f7cff 8%, transparent); }
.narration .tag, .blocked .tag {
  display: inline-block; font-size: .7rem; letter-spacing: .04em;
  padding: .1rem .4rem; border-radius: 3px; margin-bottom: .35rem;
  background: color-mix(in srgb, CanvasText 12%, transparent); }
.blocked { margin: .75rem 0 0; padding: .75rem 1rem;
  border-left: 3px solid #d08700; border-radius: 4px;
  background: color-mix(in srgb, #d08700 10%, transparent); font-size: .9rem; }
.status { margin: 1rem 0 0; padding: .75rem 1rem; border-radius: 4px;
  background: color-mix(in srgb, CanvasText 6%, transparent); font-size: .9rem; }
.status ul { margin: .4rem 0 0; padding-left: 1.2rem; }
ul.plain { padding-left: 1.2rem; }
footer { margin-top: 2.5rem; font-size: .85rem;
  color: color-mix(in srgb, CanvasText 65%, transparent); }
"""

_VERDICT_LABEL = {
    Verdict.OK: "통과",
    Verdict.ISSUE: "지적",
    Verdict.NOT_JUDGED: "판정 없음",
}


def _figure_list(lines: tuple[str, ...]) -> str:
    items = []
    for line in lines:
        text = line.lstrip("- ").strip()
        if not text:
            continue
        items.append(f"<li>{escape(text)}</li>")
    if not items:
        return "<p class='meta'>아직 계산하지 않았습니다.</p>"
    return f"<ul class='figures'>{''.join(items)}</ul>"


def render_report_html(report: FinalReport) -> str:
    """두 에이전트 판정 결과까지 보이는 보고서 페이지."""
    form = report.form
    headline_lines = form.headline.splitlines()
    title = headline_lines[0].lstrip("# ").strip() if headline_lines else "보고서"
    meta = "<br>".join(
        escape(line.lstrip("- ").strip()) for line in headline_lines[1:] if line.strip()
    )

    body: list[str] = [f"<h1>{escape(title)}</h1>"]
    if meta:
        body.append(f"<p class='meta'>{meta}</p>")

    outcomes = {item.key: item for item in report.outcomes}
    for section in form.sections:
        body.append(f"<h2>{escape(section.title)}</h2>")
        body.append(_figure_list(section.figures))
        outcome = outcomes.get(section.key)
        if section.narration:
            body.append(
                "<div class='narration'>"
                "<span class='tag'>AI 설명 · 검증 통과</span>"
                f"<div>{escape(section.narration)}</div></div>"
            )
        elif outcome is not None:
            label = _VERDICT_LABEL.get(outcome.judge_verdict, "판정 없음")
            reason = outcome.machine_reason or outcome.judge_reason or "사유 없음"
            body.append(
                "<div class='blocked'>"
                "<span class='tag'>AI 설명 미채택</span>"
                f"<div>검증 결과({escape(label)}): {escape(reason)}</div>"
                "<div class='meta'>위 수치는 계산 엔진 산출값이므로 그대로 유효합니다.</div>"
                "</div>"
            )

    if form.policy_sources:
        body.append("<h2>근거 출처</h2><ul class='plain'>")
        body.extend(f"<li>{escape(source)}</li>" for source in form.policy_sources)
        body.append("</ul>")

    verified = "모든 절이 두 에이전트 검증을 통과했습니다." if report.fully_verified else (
        f"{len(report.adopted_sections)}개 절이 검증을 통과했고, "
        f"{len(report.figures_only_sections)}개 절은 수치만 표시합니다."
    )
    status = [
        "<div class='status'><strong>검증 상태</strong>",
        f"<div>{escape(verified)}</div>",
    ]
    if report.notes:
        status.append("<ul>")
        status.extend(f"<li>{escape(note)}</li>" for note in report.notes)
        status.append("</ul>")
    status.append("</div>")
    body.extend(status)

    body.append("<footer><ul class='plain'>")
    body.extend(f"<li>{escape(note)}</li>" for note in form.disclaimers)
    body.append("</ul></footer>")

    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )


__all__ = ["render_report_html"]
