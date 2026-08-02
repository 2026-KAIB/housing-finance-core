"""PDF 경로가 실제로 동작하는지 확인한다.

PDF 생성은 글꼴이 없어도 **성공한다.** 글자만 빈 상자가 될 뿐이라 크기·형식
검사로는 잡히지 않는다. 그래서 렌더 가능 여부와 한글 글꼴 임베드를 따로 본다.

``weasyprint``는 선택 의존성(`pyproject.toml`의 `[pdf]`)이라 없는 환경도
정상이다. 그럴 때는 건너뛴다 — 없는 것을 실패로 보고하면 기본 의존성만
설치한 개발자의 전체 테스트가 빨간색이 된다.
"""

import pytest

from app.reports.pdf import (
    embedded_font_names,
    pdf_rendering_available,
    render_pdf,
    verify_korean_glyphs,
)

pytestmark = pytest.mark.skipif(
    not pdf_rendering_available(),
    reason="weasyprint가 설치되지 않았습니다. python -m pip install -e '.[pdf]'",
)

_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
body { font-family: "Noto Serif CJK KR", "Noto Sans CJK KR", serif; }
</style></head>
<body><h1>주택금융 보고서</h1><p>필요 자기자본 1억 2,000만원</p></body></html>"""


def test_rendered_pdf_is_a_pdf() -> None:
    rendered = render_pdf(_HTML)

    assert rendered.content.startswith(b"%PDF-")
    assert rendered.byte_size > 0


def test_rendered_pdf_embeds_a_korean_capable_font() -> None:
    """한글이 두부로 나가지 않는지 본다. 이 검사가 실패하면 글꼴 미설치다."""
    rendered = render_pdf(_HTML)

    verify_korean_glyphs(rendered.content)
    assert embedded_font_names(rendered.content)
