"""생애주기 곡선을 인쇄용 정적 SVG로 그린다.

목적:
    "언제까지 얼마를 모아서, 언제 사고, 언제 다 갚는가"를 한 장으로 보여준다.
    표만으로는 32년의 모양이 보이지 않는다.

왜 색으로 구분하지 않는가:
    이 문서는 **흑백 인쇄에서 모든 정보가 남아야 한다**(`official.py` 모듈
    도크스트링). 두 곡선은 **같은 먹색**이고, 구분은 **선 모양**(실선 대 파선)과
    **직접 라벨**이 한다. 색을 빼도 읽히고, 색을 넣어도 더 읽히지 않는다.

왜 CSS 클래스가 아니라 표현 속성인가:
    인쇄 엔진이 HTML 문서의 CSS를 인라인 SVG 자식에까지 적용한다는 보장이 없다.
    적용되지 않으면 획이 통째로 사라져 **빈 축만 인쇄된다** — PDF는 성공하고
    그림만 비는, 크기·형식 검사로는 잡히지 않는 실패다(한글 두부와 같은 종류).
    그래서 stroke·fill을 SVG 표현 속성으로 직접 박는다.

왜 JavaScript가 없는가:
    PDF에는 스크립트가 실행되지 않는다. 좌표를 파이썬에서 계산해 정적 SVG로
    굳힌다.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# A4 본문 폭(174mm)에 맞춘 좌표계. 실제 크기는 CSS가 정한다.
_W = 640
_H = 250
_PAD_T, _PAD_R, _PAD_B, _PAD_L = 18, 16, 30, 56
_IW = _W - _PAD_L - _PAD_R
_IH = _H - _PAD_T - _PAD_B

_HUNDRED_MILLION = Decimal("100000000")

# 두 계열이 **같은 먹색**이다. 색은 정보를 나르지 않고 선 모양이 나른다.
_INK = "#111111"
_TICK_INK = "#555555"
_GRID = "#cccccc"
_MARK = "#666666"


@dataclass(frozen=True)
class LifecyclePoint:
    """곡선 위의 한 점. ``at``은 표시용 날짜, ``amount``는 원 단위 금액이다."""

    at: date
    amount: Decimal


@dataclass(frozen=True)
class LifecycleChartInput:
    """그림 하나에 필요한 값. 모두 앞 계층이 확정한 사실이다."""

    accumulation: tuple[LifecyclePoint, ...]
    repayment: tuple[LifecyclePoint, ...]
    purchase_date: date
    maturity_value: Decimal | None = None


def _years(value: date) -> float:
    return value.year + (value.month - 1) / 12 + (value.day - 1) / 365


def _nice_ceiling(value: Decimal) -> Decimal:
    """축 상한을 1억 단위로 올린다. 눈금이 어중간하면 읽는 사람이 계산해야 한다."""
    if value <= 0:
        return _HUNDRED_MILLION
    steps = (value / _HUNDRED_MILLION).to_integral_value(rounding="ROUND_CEILING")
    return Decimal(steps) * _HUNDRED_MILLION


def _fmt_eok(value: Decimal) -> str:
    if value == 0:
        return "0"
    scaled = value / _HUNDRED_MILLION
    if scaled == scaled.to_integral_value():
        return f"{int(scaled)}억"
    return f"{scaled.quantize(Decimal('0.1'))}억"


def _fmt_won(value: Decimal) -> str:
    return f"{value.quantize(Decimal(1)):,}원"


def render_lifecycle_chart(payload: LifecycleChartInput) -> str:
    """정적 SVG 한 조각. 그릴 것이 없으면 빈 문자열을 돌려준다.

    빈 문자열을 돌려주는 이유는 호출자가 절을 통째로 건너뛸 수 있게 하기
    위해서다. 축만 있는 빈 그림은 "계산했는데 0이다"로 읽힌다.
    """
    points = payload.accumulation + payload.repayment
    if len(points) < 2:
        return ""

    t_min = min(_years(p.at) for p in points)
    t_max = max(_years(p.at) for p in points)
    if t_max <= t_min:
        return ""

    candidates = [p.amount for p in points]
    if payload.maturity_value is not None:
        candidates.append(payload.maturity_value)
    y_max = _nice_ceiling(max(candidates))

    def px(at: date) -> float:
        return _PAD_L + (_years(at) - t_min) / (t_max - t_min) * _IW

    def py(amount: Decimal) -> float:
        return _PAD_T + _IH - float(amount / y_max) * _IH

    parts: list[str] = [
        f'<svg class="lifecycle" viewBox="0 0 {_W} {_H}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="적립 기간에 모은 돈이 늘고, 매매 시점에 대출이 생겨 '
        '상환 기간에 잔액이 0으로 줄어드는 곡선">'
    ]

    # 가로 눈금 — 1억 단위
    step = _HUNDRED_MILLION
    ticks: list[Decimal] = []
    value = Decimal(0)
    while value <= y_max:
        ticks.append(value)
        value += step
    for tick in ticks:
        y = py(tick)
        stroke = _INK if tick == 0 else _GRID
        width = "0.8" if tick == 0 else "0.5"
        parts.append(
            f'<line x1="{_PAD_L}" x2="{_PAD_L + _IW}" y1="{y:.1f}" y2="{y:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}"/>'
        )
        parts.append(
            f'<text x="{_PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'fill="{_TICK_INK}" font-size="8">{_fmt_eok(tick)}</text>'
        )

    # 세로 눈금 — 연도. 5년 간격으로 잡되 양 끝은 반드시 찍는다.
    first_year = int(t_min) + 1
    last_year = int(t_max)
    years = [y for y in range(first_year, last_year + 1) if (y - first_year) % 5 == 0]
    if last_year not in years:
        years.append(last_year)
    for year in years:
        x = _PAD_L + (year - t_min) / (t_max - t_min) * _IW
        parts.append(
            f'<text x="{x:.1f}" y="{_PAD_T + _IH + 20}" text-anchor="middle" '
            f'fill="{_TICK_INK}" font-size="8">{year}</text>'
        )

    def label(x: float, y: float, anchor: str, text: str, muted: bool = False) -> None:
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
            f'fill="{_TICK_INK if muted else _INK}" font-size="{8 if muted else 8.5}" '
            f'font-weight="{400 if muted else 600}">{text}</text>'
        )

    # 매매 시점 — 두 곡선이 갈리는 자리
    purchase_x = px(payload.purchase_date)
    parts.append(
        f'<line x1="{purchase_x:.1f}" x2="{purchase_x:.1f}" y1="{_PAD_T}" '
        f'y2="{_PAD_T + _IH}" stroke="{_MARK}" stroke-width="0.8" '
        'stroke-dasharray="3 2"/>'
    )
    label(purchase_x + 5, _PAD_T + 10, "start", f"매매 {payload.purchase_date.isoformat()}")

    def polyline(series: tuple[LifecyclePoint, ...], dashed: bool) -> None:
        if len(series) < 2:
            return
        coords = " ".join(f"{px(p.at):.1f},{py(p.amount):.1f}" for p in series)
        dash = ' stroke-dasharray="6 3"' if dashed else ""
        parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{_INK}" '
            f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"{dash}/>'
        )

    polyline(payload.accumulation, dashed=False)
    polyline(payload.repayment, dashed=True)

    # 직접 라벨 — 색이 아니라 글자와 선 모양이 계열을 가른다.
    if payload.accumulation:
        peak = payload.accumulation[-1]
        label(px(peak.at) - 6, py(peak.amount) - 8, "end", f"모은 돈 {_fmt_won(peak.amount)}")
    if payload.repayment:
        head = payload.repayment[0]
        label(px(head.at) + 5, py(head.amount) - 8, "start", f"남은 빚 {_fmt_won(head.amount)}")
        tail = payload.repayment[-1]
        label(
            px(tail.at), py(tail.amount) - 8, "end",
            f"상환 완료 {tail.at.isoformat()}", muted=True,
        )

    parts.append("</svg>")
    return "".join(parts)


# 획·글자 색은 SVG 표현 속성이 직접 들고 있다(위 모듈 도크스트링 참조).
# 여기서는 **배치만** 정한다 — 이 규칙이 적용되지 않아도 그림은 그대로 보인다.
LIFECYCLE_STYLE = """
svg.lifecycle { width: 100%; height: auto; margin: 2mm 0 3mm;
  page-break-inside: avoid; }
"""

__all__ = [
    "LIFECYCLE_STYLE",
    "LifecycleChartInput",
    "LifecyclePoint",
    "render_lifecycle_chart",
]
