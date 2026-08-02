"""PDF 보관 경로.

이 파일은 **WeasyPrint 없이도** 돈다. 렌더링 엔진은 시스템 라이브러리를 요구해서
CI와 Windows 로컬에는 없다. 엔진이 있는 환경에서만 도는 검사는 맨 아래에 따로 둔다.

고정하는 불변식:
1. 보관은 꺼져 있는 것이 기본이며, 꺼진 것과 고장난 것을 가른다.
2. 저장 경로에 사용자 입력이 섞이지 않고, 루트를 벗어나지 못한다.
3. 보관된 문서는 덮어써지지 않고, 손상되면 조용히 나가지 않는다.
4. 한글 글꼴이 없는 PDF는 "성공"이 아니다.
5. ``filesystem`` 보관은 DB 없이 완결된다 — 색인 한 줄을 남기지 못했다는 이유로
   이미 디스크에 안전하게 저장된 문서를 버리지 않는다.
"""

import logging
import zlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine

from app.core.config import Settings
from app.db.models.report import report_metadata
from app.db.repositories.report_repository import (
    ReportRecord,
    fetch_report,
    insert_report,
)
from app.reports.pdf import (
    PdfRenderingUnavailable,
    embedded_font_names,
    render_pdf,
    verify_korean_glyphs,
)
from app.reports.storage import (
    ReportStorageError,
    build_record_path,
    build_relative_path,
    content_digest,
    load_bytes,
    read_if_present,
    store_bytes,
)
from app.services.report_archive import (
    ReportArchiveDisabled,
    _index_in_database,
    archive_pdf_report,
    load_archived_pdf,
)

REPORT_ID = UUID("6d1f5f6a-63a0-4a6f-9c69-6f0a6a4b2c11")
SOURCE_ID = UUID("9a2b7c1d-4e5f-4a3b-8c9d-0e1f2a3b4c5d")
AS_OF = date(2026, 8, 1)
CREATED_AT = datetime(2026, 8, 1, 9, tzinfo=UTC)
PDF_BYTES = b"%PDF-1.7\n" + b"x" * 512


def _settings(root: Path, provider: str = "filesystem") -> Settings:
    return Settings(
        report_archive_provider=provider,
        report_storage_root=root,
    )


def _sqlite_engine():
    engine = create_engine("sqlite://")
    report_metadata.create_all(engine)
    return engine


# --------------------------------------------------------------------------
# 꺼진 것과 고장난 것
# --------------------------------------------------------------------------


def test_archiving_is_off_by_default() -> None:
    """기본값이 켜져 있으면 계산 한 번에 개인 재무 문서가 디스크에 쌓인다."""
    assert Settings().report_archive_provider == "none"


def test_a_disabled_archive_is_not_a_failure(tmp_path: Path) -> None:
    with pytest.raises(ReportArchiveDisabled):
        archive_pdf_report(
            "<p>x</p>",
            report_id=REPORT_ID,
            kind="simulation",
            source_id=SOURCE_ID,
            created_at=CREATED_AT,
            as_of=AS_OF,
            fully_verified=True,
            config=_settings(tmp_path, provider="none"),
        )


# --------------------------------------------------------------------------
# 저장 경로
# --------------------------------------------------------------------------


def test_the_stored_path_is_built_from_the_server_made_id() -> None:
    """파일명이 입력에서 오면 매물명·사용자명이 그대로 새고 ``../``도 들어온다."""
    assert build_relative_path(REPORT_ID, as_of=AS_OF) == f"2026/08/{REPORT_ID}.pdf"


def test_the_record_path_is_derivable_from_the_id_alone() -> None:
    """조회는 ``GET /{id}.pdf``로 들어와 기준일을 모른다.

    기록 경로가 본문처럼 ``as_of``에 의존하면 id에서 경로를 되찾을 수 없어, 기록을
    찾으려고 저장소 전체를 훑어야 한다.
    """
    assert build_record_path(REPORT_ID) == f"records/6d/{REPORT_ID}.json"


def test_an_absent_file_is_none_not_a_read_failure(tmp_path: Path) -> None:
    """없음을 읽기 실패로 뭉개면 오타 난 문서번호가 서버 장애(503)로 보인다."""
    assert read_if_present(root=tmp_path, relative_path="records/aa/absent.json") is None


def test_a_path_escaping_the_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ReportStorageError):
        store_bytes(PDF_BYTES, root=tmp_path, relative_path="../escaped.pdf")


def test_storing_the_same_id_twice_is_an_error_not_an_overwrite(tmp_path: Path) -> None:
    """보관된 문서가 사후에 바뀌면 이미 전달한 문서와 내용이 갈린다."""
    relative = build_relative_path(REPORT_ID, as_of=AS_OF)
    store_bytes(PDF_BYTES, root=tmp_path, relative_path=relative)

    with pytest.raises(ReportStorageError):
        store_bytes(b"%PDF-1.7\nother", root=tmp_path, relative_path=relative)


def test_an_empty_document_is_not_stored(tmp_path: Path) -> None:
    with pytest.raises(ReportStorageError):
        store_bytes(b"", root=tmp_path, relative_path="a.pdf")


def test_a_corrupted_file_does_not_leave_the_server(tmp_path: Path) -> None:
    """해시가 다른 파일을 원본인 척 내보내면 사용자는 다른 문서를 받는다."""
    relative = build_relative_path(REPORT_ID, as_of=AS_OF)
    stored = store_bytes(PDF_BYTES, root=tmp_path, relative_path=relative)
    (tmp_path / relative).write_bytes(b"%PDF-1.7\ntampered")

    with pytest.raises(ReportStorageError):
        load_bytes(
            root=tmp_path,
            relative_path=relative,
            expected_sha256=stored.content_sha256,
        )


def test_an_intact_file_round_trips(tmp_path: Path) -> None:
    relative = build_relative_path(REPORT_ID, as_of=AS_OF)
    stored = store_bytes(PDF_BYTES, root=tmp_path, relative_path=relative)

    assert stored.content_sha256 == content_digest(PDF_BYTES)
    assert (
        load_bytes(
            root=tmp_path, relative_path=relative, expected_sha256=stored.content_sha256
        )
        == PDF_BYTES
    )


# --------------------------------------------------------------------------
# 메타데이터
# --------------------------------------------------------------------------


def _record(**changes: object) -> ReportRecord:
    values: dict[str, object] = {
        "id": REPORT_ID,
        "kind": "simulation",
        "source_id": SOURCE_ID,
        "created_at": CREATED_AT,
        "as_of": AS_OF,
        "media_type": "application/pdf",
        "byte_size": len(PDF_BYTES),
        "content_sha256": content_digest(PDF_BYTES),
        "storage_path": build_relative_path(REPORT_ID, as_of=AS_OF),
        "fully_verified": False,
        "adopted_sections": ("rates_and_policy",),
        "figures_only_sections": ("decision_reasons",),
        "policy_sources": ("예금자보호법 시행령(시행 2025-09-01)",),
        "notes": ("검증 에이전트 판정 없음",),
    }
    values.update(changes)
    return ReportRecord(**values)  # type: ignore[arg-type]


def test_the_record_keeps_what_the_file_alone_cannot_answer() -> None:
    """as_of와 채택 내역을 잃으면 "이 문서는 언제 기준이며 믿을 수 있나"에 답할 수 없다."""
    engine = _sqlite_engine()
    with engine.begin() as connection:
        insert_report(connection, _record())
    with engine.connect() as connection:
        found = fetch_report(connection, REPORT_ID)

    assert found is not None
    assert found.as_of == AS_OF
    assert found.fully_verified is False
    assert found.figures_only_sections == ("decision_reasons",)
    assert found.policy_sources == ("예금자보호법 시행령(시행 2025-09-01)",)


def test_an_unknown_id_is_absent_not_an_error() -> None:
    engine = _sqlite_engine()
    with engine.connect() as connection:
        assert fetch_report(connection, uuid4()) is None


def test_a_missing_record_is_reported_as_missing(tmp_path: Path) -> None:
    with pytest.raises(LookupError):
        load_archived_pdf(uuid4(), config=_settings(tmp_path))


def test_a_corrupted_record_does_not_become_a_default(tmp_path: Path) -> None:
    """형식이 깨진 기록을 기본값으로 메우면 기준일이 사실과 다른 문서가 나간다."""
    store_bytes(
        b"{ this is not json",
        root=tmp_path,
        relative_path=build_record_path(REPORT_ID),
    )

    with pytest.raises(ReportStorageError):
        load_archived_pdf(REPORT_ID, config=_settings(tmp_path))


# --------------------------------------------------------------------------
# DB 색인은 부차적이다
# --------------------------------------------------------------------------


def test_a_failed_database_index_does_not_discard_the_document(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """색인 한 줄을 남기지 못한 것과 문서를 만들지 못한 것은 다른 상태다.

    예전에는 이 실패가 503이 되어, 이미 렌더링·글꼴 검사를 통과해 디스크에 저장된
    보고서를 통째로 버렸다.
    """
    engine = create_engine("sqlite://")  # reports 테이블을 만들지 않았다

    with caplog.at_level(logging.ERROR):
        _index_in_database(_record(), engine)

    assert "not indexed in the database" in caplog.text


def test_the_index_failure_log_does_not_carry_driver_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """드라이버 오류 문자열에는 접속 호스트·사용자명이 섞여 나온다."""
    engine = create_engine("sqlite://")

    with caplog.at_level(logging.ERROR):
        _index_in_database(_record(), engine)

    assert "no such table" not in caplog.text


# --------------------------------------------------------------------------
# 한글 글꼴 — PDF는 폰트가 없어도 "성공"한다
# --------------------------------------------------------------------------


def test_font_names_are_read_without_their_subset_prefix() -> None:
    content = b"%PDF-1.7\n/BaseFont /ABCDEF+NotoSerifCJKKR-Regular\n"

    assert embedded_font_names(content) == frozenset({"NotoSerifCJKKR-Regular"})


def test_a_pdf_without_any_korean_capable_font_is_refused() -> None:
    """폰트가 없으면 글자만 빈 상자가 되고 크기·형식 검사는 통과한다."""
    latin_only = b"%PDF-1.7\n/BaseFont /ABCDEF+DejaVuSans\n"

    with pytest.raises(PdfRenderingUnavailable, match="한글"):
        verify_korean_glyphs(latin_only)


def test_a_pdf_with_no_embedded_font_at_all_is_refused() -> None:
    with pytest.raises(PdfRenderingUnavailable, match="임베드된 폰트가 없습니다"):
        verify_korean_glyphs(b"%PDF-1.7\nnothing here\n")


def test_a_cjk_font_passes() -> None:
    verify_korean_glyphs(b"%PDF-1.7\n/BaseFont /ABCDEF+NotoSansCJKKR-Regular\n")


def _compressed_pdf(*base_fonts: str) -> bytes:
    """폰트 딕셔너리를 **압축된 객체 스트림에 넣은** PDF를 흉내 낸다.

    WeasyPrint의 기본 출력이 이 모양이라 ``/BaseFont``가 평문으로는 한 번도
    나타나지 않는다. 여기서 재현하지 않으면 이 실패는 엔진이 있는 환경에서만
    드러나고, 그 검사들은 로컬에서 전부 skip이라 CI에 가서야 터진다.
    """
    objects = b" ".join(
        f"<</Type/Font/Subtype/Type0/BaseFont /ABCDEF+{name}>>".encode() for name in base_fonts
    )
    return (
        b"%PDF-1.7\n%\xf0\x9f\x96\xa4\n"
        b"5 0 obj\n<</Type /ObjStm/Filter /FlateDecode>>\nstream\n"
        + zlib.compress(b"1 0 2 60 " + objects)
        + b"\nendstream\nendobj\nstartxref\n112496\n%%EOF\n"
    )


def test_fonts_hidden_inside_a_compressed_object_stream_are_still_found() -> None:
    """평문만 훑으면 정상 문서를 "폰트 없음"으로 막는다. 실제로 CI에서 그랬다."""
    content = _compressed_pdf("NotoSerifCJKKR-Regular")

    assert b"/BaseFont" not in content, "평문으로 보이면 이 검사가 아무것도 증명하지 않는다"
    assert embedded_font_names(content) == frozenset({"NotoSerifCJKKR-Regular"})
    verify_korean_glyphs(content)


def test_a_compressed_pdf_without_a_korean_font_is_still_refused() -> None:
    """압축을 푸는 것이 검사를 무디게 만들지 않는지 확인한다."""
    with pytest.raises(PdfRenderingUnavailable, match="한글"):
        verify_korean_glyphs(_compressed_pdf("DejaVuSans", "DejaVuSans-Bold"))


def test_a_stream_that_is_not_compressed_does_not_break_the_scan() -> None:
    """이미지·폰트 본문처럼 zlib이 아닌 스트림이 섞여도 훑기가 멈추면 안 된다."""
    content = (
        b"%PDF-1.7\n7 0 obj\n<</Length 8>>\nstream\n\x00\x01\x02\x03rawbytes\nendstream\nendobj\n"
        + _compressed_pdf("NotoSansCJKKR-Regular")[9:]
    )

    assert embedded_font_names(content) == frozenset({"NotoSansCJKKR-Regular"})


# --------------------------------------------------------------------------
# 엔진이 있는 환경에서만
# --------------------------------------------------------------------------


def _engine_missing() -> bool:
    try:
        render_pdf("<p>.</p>")
    except PdfRenderingUnavailable:
        return True
    return False


@pytest.mark.skipif(_engine_missing(), reason="WeasyPrint를 쓸 수 없는 환경")
def test_korean_text_renders_with_a_korean_font() -> None:
    """이 검사가 도는 환경에서만 "두부가 아니다"를 실제로 증명할 수 있다."""
    rendered = render_pdf(
        "<html><body><p>대출 가능액은 확인이 필요합니다.</p></body></html>"
    )

    assert rendered.content.startswith(b"%PDF")
    verify_korean_glyphs(rendered.content)


@pytest.mark.skipif(_engine_missing(), reason="WeasyPrint를 쓸 수 없는 환경")
def test_archiving_round_trips_through_storage_and_the_record(tmp_path: Path) -> None:
    engine = _sqlite_engine()
    config = _settings(tmp_path)
    report_id = uuid4()

    record = archive_pdf_report(
        "<html><body><p>보관 확인용 문서입니다.</p></body></html>",
        report_id=report_id,
        kind="simulation",
        source_id=SOURCE_ID,
        created_at=CREATED_AT,
        as_of=AS_OF,
        fully_verified=True,
        config=config,
        engine=engine,
    )
    found, content = load_archived_pdf(report_id, config=config)

    assert found.content_sha256 == record.content_sha256
    assert content.startswith(b"%PDF")
    assert Decimal(found.byte_size) > 0


@pytest.mark.skipif(_engine_missing(), reason="WeasyPrint를 쓸 수 없는 환경")
def test_a_report_is_archived_and_read_back_without_any_database(tmp_path: Path) -> None:
    """``filesystem`` 공급원은 이름 그대로 파일시스템만으로 완결된다.

    DB에 닿지 못하는 것은 흔한 상태다(터널이 닫혀 있는 개발 환경). 그때 보고서를
    못 만드는 것이 아니라, 만들어 놓고 못 꺼내는 것이 문제였다.
    """
    config = _settings(tmp_path)
    report_id = uuid4()

    record = archive_pdf_report(
        "<html><body><p>DB 없이 보관되는 문서입니다.</p></body></html>",
        report_id=report_id,
        kind="simulation",
        source_id=SOURCE_ID,
        created_at=CREATED_AT,
        as_of=AS_OF,
        fully_verified=True,
        adopted_sections=("rates_and_policy",),
        policy_sources=("예금자보호법 시행령(시행 2025-09-01)",),
        config=config,
        # 색인은 실패한다 — reports 테이블이 없다.
        engine=create_engine("sqlite://"),
    )
    found, content = load_archived_pdf(report_id, config=config)

    assert content.startswith(b"%PDF")
    assert found.as_of == AS_OF
    assert found.content_sha256 == record.content_sha256
    assert found.adopted_sections == ("rates_and_policy",)
    assert found.policy_sources == ("예금자보호법 시행령(시행 2025-09-01)",)
