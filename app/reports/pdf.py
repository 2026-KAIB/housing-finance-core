"""인쇄용 HTML 보고서를 PDF 바이트로 굳힌다.

목적:
    ``templates/official.py``가 만드는 문서는 **인쇄해서 남기는 것**이다. 화면에서
    한 번 보고 버리는 것이 아니라 보관·전달되는 산출물이므로, 렌더링 환경에 따라
    달라지지 않는 고정 포맷이 필요하다.

왜 WeasyPrint인가:
    ``official.py``는 처음부터 ``@page`` 여백 상자에 쪽 번호를 넣어 두고, 브라우저는
    그것을 렌더링하지 않는다고 그 파일이 스스로 밝히고 있다(``official.py`` 모듈
    도크스트링). 브라우저 엔진(Playwright 등)으로 굽으면 이미 쓰여 있는 쪽 번호
    규칙이 조용히 사라진다. WeasyPrint는 그 규칙을 그대로 렌더링한다.

없을 때 무엇을 하는가:
    WeasyPrint는 Pango·cairo 같은 **시스템 라이브러리**를 필요로 해서 Windows
    로컬에는 보통 없다. 그래서 import를 함수 안으로 미루고, 없으면 조용히 빈
    바이트를 돌려주는 대신 ``PdfRenderingUnavailable``로 **막는다.** 빈 PDF나
    깨진 PDF를 성공으로 취급하면 보관된 문서가 열리지 않는 채로 쌓인다.

한글 폰트:
    이 문서의 실패 1순위는 계산이 아니라 **두부(□□□)** 다. 컨테이너에 CJK 폰트가
    없으면 모든 글자가 빈 상자로 나오는데, PDF 생성 자체는 성공하므로 검사 없이는
    드러나지 않는다. ``verify_korean_glyphs``가 그 눈을 대신한다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 인쇄 문서가 기대는 한글 글꼴 계열. Debian/Ubuntu의 ``fonts-noto-cjk``가 설치하는
# 실제 패밀리 이름은 "Noto Sans CJK KR"이며 "Noto Sans KR"이 **아니다.** 이름을
# 틀리면 폰트가 설치돼 있어도 fontconfig가 못 찾아 두부가 난다.
KOREAN_FONT_FAMILIES = (
    "Noto Serif CJK KR",
    "Noto Sans CJK KR",
    "Malgun Gothic",
)


class PdfRenderingUnavailable(RuntimeError):
    """PDF 렌더링 엔진을 쓸 수 없다.

    "PDF를 만들지 못했다"와 "PDF가 필요 없다"는 다른 상태다. 이 예외는 앞의 것만
    가리키며, 호출자는 이것을 빈 결과로 바꾸지 않는다.
    """


@dataclass(frozen=True)
class RenderedPdf:
    content: bytes
    engine: str

    @property
    def byte_size(self) -> int:
        return len(self.content)


def render_pdf(html: str, *, base_url: str | None = None) -> RenderedPdf:
    """인쇄용 HTML을 PDF 바이트로 만든다.

    ``base_url``은 문서가 상대 경로 자원을 참조할 때만 필요하다. 지금 문서는
    이미지·외부 스타일시트를 쓰지 않으므로 기본값 ``None``으로 충분하며, 그 덕에
    렌더링 중 네트워크·파일시스템 접근이 일어나지 않는다.
    """
    try:
        from weasyprint import HTML  # noqa: PLC0415 - 시스템 라이브러리 의존이라 지연 import
    except OSError as exc:
        # cffi가 libpango/libgobject를 못 열면 ImportError가 아니라 OSError다.
        raise PdfRenderingUnavailable(
            "PDF 렌더링에 필요한 시스템 라이브러리(Pango/cairo)를 찾지 못했습니다."
        ) from exc
    except ImportError as exc:
        raise PdfRenderingUnavailable(
            "PDF 렌더링 엔진(WeasyPrint)이 설치되어 있지 않습니다."
        ) from exc

    document = HTML(string=html, base_url=base_url)
    content = document.write_pdf()
    if not content or not content.startswith(b"%PDF"):
        raise PdfRenderingUnavailable("PDF 렌더링 결과가 올바른 PDF가 아닙니다.")
    return RenderedPdf(content=content, engine="weasyprint")


def pdf_rendering_available() -> bool:
    """엔진을 쓸 수 있는지만 본다. 설정 화면과 기동 점검용이다."""
    try:
        render_pdf("<p>.</p>")
    except PdfRenderingUnavailable:
        return False
    return True


def embedded_font_names(content: bytes) -> frozenset[str]:
    """PDF에 실제로 **임베드된** 폰트 이름을 긁는다.

    폰트 딕셔너리의 ``/BaseFont /ABCDEF+NotoSerifCJKKR-Regular`` 형태를 찾는다.
    부분집합 접두사(``ABCDEF+``)는 떼고 돌려준다.
    """
    names: set[str] = set()
    marker = b"/BaseFont"
    start = content.find(marker)
    while start != -1:
        cursor = content.find(b"/", start + len(marker))
        if cursor == -1:
            break
        end = cursor + 1
        while end < len(content) and content[end : end + 1] not in b"/ \t\r\n>[]()<":
            end += 1
        raw = content[cursor + 1 : end].decode("latin-1", errors="ignore")
        names.add(raw.split("+", 1)[-1])
        start = content.find(marker, end)
    return frozenset(names)


def verify_korean_glyphs(content: bytes) -> None:
    """한글이 글꼴 없이 두부로 나가지 않았는지 확인한다.

    PDF 생성은 폰트가 없어도 **성공한다.** 글자만 빈 상자가 될 뿐이라 크기·형식
    검사로는 절대 잡히지 않는다. 그래서 임베드된 폰트 이름에 CJK 계열이 있는지를
    본다 — 한글을 그릴 수 있는 폰트가 하나도 안 붙었다면 그 문서는 못 읽는다.

    완전한 검사는 아니다(글리프 단위로 열어 보지는 않는다). 그러나 "컨테이너에
    CJK 폰트를 안 깔았다"는 실제 실패 모드는 여기서 전부 걸린다.
    """
    fonts = embedded_font_names(content)
    if not fonts:
        raise PdfRenderingUnavailable(
            "PDF에 임베드된 폰트가 없습니다 — 한글이 표시되지 않습니다."
        )
    if not any(_looks_korean_capable(name) for name in fonts):
        raise PdfRenderingUnavailable(
            "PDF에 한글을 그릴 수 있는 글꼴이 임베드되지 않았습니다. "
            f"임베드된 글꼴: {sorted(fonts)}. "
            "컨테이너에 fonts-noto-cjk를 설치했는지 확인하십시오."
        )


def _looks_korean_capable(font_name: str) -> bool:
    lowered = font_name.lower().replace(" ", "").replace("-", "")
    return any(
        token in lowered
        for token in ("cjk", "malgun", "nanum", "gothic", "batang", "gulim", "dotum")
    )


__all__ = [
    "KOREAN_FONT_FAMILIES",
    "PdfRenderingUnavailable",
    "RenderedPdf",
    "embedded_font_names",
    "pdf_rendering_available",
    "render_pdf",
    "verify_korean_glyphs",
]
