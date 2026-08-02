"""생애주기 곡선 — 인쇄 문서에 들어가는 그림.

이 문서의 규약은 **흑백 인쇄에서 모든 정보가 남는 것**이다(`official.py` 모듈
도크스트링). 그래서 여기서 고정하는 첫 번째 불변식은 "색으로 정보를 전달하지
않는다"이고, 두 번째는 "모르는 구간을 보간하지 않는다"이다.
"""

import re
from datetime import date
from decimal import Decimal

import pytest

from app.reports.lifecycle_view import build_lifecycle_chart_input
from app.reports.pdf import pdf_rendering_available, render_pdf
from app.reports.templates.lifecycle_chart import (
    LIFECYCLE_STYLE,
    LifecycleChartInput,
    LifecyclePoint,
    render_lifecycle_chart,
)
from app.schemas.simulation import SectionRunStatus, SimulationResult
from app.services.simulation_result import build_calculation_section

AS_OF = date(2026, 8, 1)
PURCHASE = date(2028, 8, 1)


def _accumulation(months: int = 24, monthly: int = 1_200_000) -> tuple[LifecyclePoint, ...]:
    rows = [LifecyclePoint(at=AS_OF, amount=Decimal(0))]
    for index in range(1, months + 1):
        total = index * 12
        rows.append(
            LifecyclePoint(
                at=date(AS_OF.year + (AS_OF.month - 1 + index) // 12,
                        (AS_OF.month - 1 + index) % 12 + 1, 1),
                amount=Decimal(monthly * index),
            )
        )
        del total
    return tuple(rows)


def _repayment(points: int = 61, start: int = 310_000_000) -> tuple[LifecyclePoint, ...]:
    rows = []
    for index in range(points):
        rows.append(
            LifecyclePoint(
                at=date(PURCHASE.year + index // 2, 8 if index % 2 == 0 else 2, 1),
                amount=Decimal(start) - Decimal(start) * index // (points - 1),
            )
        )
    return tuple(rows)


def _chart(**changes: object) -> str:
    values: dict[str, object] = {
        "accumulation": _accumulation(),
        "repayment": _repayment(),
        "purchase_date": PURCHASE,
        "maturity_value": Decimal("91203622"),
    }
    values.update(changes)
    return render_lifecycle_chart(LifecycleChartInput(**values))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# 흑백에서 읽힌다
# --------------------------------------------------------------------------


def test_the_two_series_share_one_ink_so_colour_carries_nothing() -> None:
    """흑백 인쇄에서 정보가 사라지면 안 된다.

    "색을 안 쓴다"가 아니라 **두 계열이 같은 색**이라는 것이 지켜야 할 성질이다.
    색이 같으면 색을 빼도 잃는 정보가 없다.
    """
    svg = _chart()
    strokes = re.findall(r'<polyline[^>]*stroke="([^"]+)"', svg)

    assert len(strokes) == 2
    assert strokes[0] == strokes[1]


def test_the_two_series_are_told_apart_by_line_shape() -> None:
    """구분은 실선과 파선이 한다."""
    svg = _chart()
    lines = re.findall(r"<polyline[^>]*/>", svg)

    assert len(lines) == 2
    assert sum("stroke-dasharray" in line for line in lines) == 1


def test_strokes_are_presentation_attributes_not_css_classes() -> None:
    """인쇄 엔진이 문서 CSS를 인라인 SVG에 적용한다는 보장이 없다.

    적용되지 않으면 획이 사라져 **빈 축만 인쇄된다** — PDF는 성공하고 그림만
    비는, 크기·형식 검사로는 잡히지 않는 실패다.
    """
    svg = _chart()

    for line in re.findall(r"<polyline[^>]*/>", svg):
        assert "stroke=" in line
        assert "stroke-width=" in line
    assert 'class="lc-' not in svg


def test_each_series_carries_its_own_label() -> None:
    """범례 없이 그림만 봐도 어느 선이 무엇인지 읽혀야 한다."""
    svg = _chart()

    assert "모은 돈" in svg
    assert "남은 빚" in svg
    assert "상환 완료" in svg


def test_the_purchase_moment_is_marked() -> None:
    svg = _chart()

    assert "매매 2028-08-01" in svg
    assert svg.count("stroke-dasharray") >= 2  # 매매 세로선 + 상환 곡선


@pytest.mark.skipif(
    not pdf_rendering_available(), reason="weasyprint가 없는 환경"
)
def test_the_chart_actually_survives_the_pdf_engine() -> None:
    """그림이 PDF에 실제로 그려지는지는 **구워 봐야만** 알 수 있다.

    인쇄 엔진이 SVG를 무시하거나 스타일을 못 받으면 빈 자리만 남는데, 그건 이
    저장소가 이미 한 번 겪은 실패(한글 두부)와 같은 종류다 — PDF 생성은 성공하고
    내용만 빈다. 개발자 로컬에는 엔진이 없으므로 CI의 ``pdf`` 잡이 이걸 본다.
    """
    svg = _chart()
    html = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        f"<style>{LIFECYCLE_STYLE}</style></head><body>{svg}</body></html>"
    )
    rendered = render_pdf(html)

    assert rendered.content.startswith(b"%PDF")
    # 축·곡선이 통째로 빠지면 스트림이 눈에 띄게 작아진다. 빈 문서와 구분한다.
    empty = render_pdf(
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "</head><body></body></html>"
    )
    assert rendered.byte_size > empty.byte_size


# --------------------------------------------------------------------------
# 그릴 수 없으면 그리지 않는다
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("accumulation", "repayment"),
    [((), ()), (_accumulation(), ()), ((), ())],
)
def test_too_few_points_render_nothing(
    accumulation: tuple[LifecyclePoint, ...],
    repayment: tuple[LifecyclePoint, ...],
) -> None:
    """축만 있는 빈 그림은 "계산했는데 0이다"로 읽힌다. 아무것도 내지 않는다."""
    if len(accumulation) + len(repayment) >= 2:
        pytest.skip("이 조합은 그릴 수 있다")
    assert _chart(accumulation=accumulation, repayment=repayment) == ""


def test_the_axis_ceiling_is_a_round_hundred_million() -> None:
    """눈금이 어중간하면 읽는 사람이 계산해야 한다."""
    svg = _chart()
    texts = re.findall(r"<text[^>]*>([^<]+)</text>", svg)

    assert "0" in texts
    assert any(text.endswith("억") for text in texts)


def test_the_chart_survives_a_single_phase() -> None:
    """적립만 있고 대출이 없어도 그림은 성립한다."""
    svg = _chart(repayment=(), maturity_value=None)

    assert svg.count("<polyline") == 1
    assert "모은 돈" in svg


# --------------------------------------------------------------------------
# 계산 결과에서 뽑을 때 — 모르는 구간을 보간하지 않는다
# --------------------------------------------------------------------------


def _with_savings(simulation: SimulationResult, allocations: list[dict]) -> SimulationResult:
    section = build_calculation_section(
        {"allocations": allocations},
        section_schema_version="savings-portfolio@1.1.0",
    )
    return simulation.model_copy(update={"savings_portfolio": section})


def test_the_accumulation_curve_is_contributed_principal_only(
    simulation: SimulationResult,
) -> None:
    """배분 결과에 이율이 없다. 중간 시점 평가액을 만들면 그건 지어낸 값이다.

    확정된 납입 원금만 그리고, 만기 평가액은 그 시점 값 하나로만 밝힌다.
    """
    payload = build_lifecycle_chart_input(
        _with_savings(
            simulation,
            [
                {
                    "allocation_basis": "MONTHLY",
                    "allocation_amount": "1000000",
                    "term_months": 24,
                    "expected_maturity_amount": "25000000",
                }
            ],
        )
    )

    assert payload is not None
    assert payload.accumulation[0].amount == Decimal(0)
    # 12개월째 값이 정확히 납입 원금이다 — 이자가 섞여 있으면 더 크다.
    assert payload.accumulation[12].amount == Decimal("12000000")
    assert payload.maturity_value == Decimal("25000000")


def test_a_lump_sum_deposit_is_not_added_every_month(
    simulation: SimulationResult,
) -> None:
    """예금은 한 번 넣는다. 매달 더하면 24개월 뒤 원금이 24배가 된다."""
    payload = build_lifecycle_chart_input(
        _with_savings(
            simulation,
            [
                {
                    "allocation_basis": "LUMP_SUM",
                    "allocation_amount": "50000000",
                    "term_months": 24,
                    "expected_maturity_amount": "53000000",
                }
            ],
        )
    )

    assert payload is not None
    assert payload.accumulation[1].amount == Decimal("50000000")
    assert payload.accumulation[-1].amount == Decimal("50000000")


def test_no_combination_means_no_chart(simulation: SimulationResult) -> None:
    """조달방안이 없으면 상환 곡선이 성립하지 않는다."""
    stripped = simulation.model_copy(
        update={
            "loan_combination": build_calculation_section(
                None, section_schema_version="loan-combination@1.0.0"
            )
        }
    )

    assert build_lifecycle_chart_input(stripped) is None


def test_the_section_keeps_its_place_when_there_is_nothing_to_draw(
    simulation: SimulationResult,
) -> None:
    """절 번호는 입력에 따라 밀리지 않는다. 자리를 지키고 사유를 적는다."""
    from app.reports.templates.official import _lifecycle

    stripped = simulation.model_copy(
        update={
            "loan_combination": build_calculation_section(
                None, section_schema_version="loan-combination@1.0.0"
            )
        }
    )
    body = _lifecycle(stripped)

    assert "<h2>3. 생애주기</h2>" in body
    assert "그리지 않았습니다" in body
    assert simulation.loan_combination.run_status is SectionRunStatus.COMPLETED
