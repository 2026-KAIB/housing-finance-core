"""보고서를 PDF로 굳혀 보관하고 다시 꺼낸다.

흐름:
    인쇄용 HTML → PDF 렌더링 → 한글 글꼴 확인 → 파일 저장 → 메타데이터 행 삽입

왜 순서가 이런가:
    행을 먼저 넣고 파일을 쓰면, 파일 쓰기가 실패했을 때 **가리키는 파일이 없는 행**이
    남는다. 반대로 파일을 먼저 쓰고 행 삽입이 실패하면 주인 없는 파일이 남는데,
    그건 조회되지 않을 뿐 아무에게도 잘못된 답을 주지 않는다. 둘 중 덜 위험한 쪽을
    고른다.

왜 글꼴을 여기서 확인하는가:
    PDF는 폰트가 없어도 **성공적으로** 만들어진다. 글자만 빈 상자가 될 뿐이다.
    보관은 되돌리기 어려우므로, 읽을 수 없는 문서를 쌓기 전에 막는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.repositories.report_repository import (
    ReportRecord,
    fetch_report,
    insert_report,
)
from app.db.session import DatabaseConfigurationError, get_database_engine
from app.reports.pdf import (
    PdfRenderingUnavailable,
    render_pdf,
    verify_korean_glyphs,
)
from app.reports.storage import (
    ReportStorageError,
    build_relative_path,
    load_bytes,
    store_bytes,
)

PDF_MEDIA_TYPE = "application/pdf"


class ReportArchiveDisabled(RuntimeError):
    """보관 기능이 꺼져 있다.

    **고장난 것이 아니다.** 공급원을 설정하지 않은 것과 설정한 공급원이 고장 난
    것을 가르기 위해 별도 예외로 둔다(예·적금 카탈로그와 같은 규약).
    """


class ReportArchiveUnavailable(RuntimeError):
    """보관 기능이 켜져 있는데 쓸 수 없다."""


def _archive_root(config: Settings) -> Path:
    if config.report_archive_provider != "filesystem":
        raise ReportArchiveDisabled(
            f"보고서 보관 공급원이 설정되지 않았습니다: {config.report_archive_provider}"
        )
    return config.report_storage_root


def archive_pdf_report(
    html: str,
    *,
    report_id: UUID,
    kind: str,
    source_id: UUID,
    created_at: datetime,
    as_of: date,
    fully_verified: bool,
    adopted_sections: Sequence[str] = (),
    figures_only_sections: Sequence[str] = (),
    policy_sources: Sequence[str] = (),
    notes: Sequence[str] = (),
    config: Settings | None = None,
    engine: Engine | None = None,
) -> ReportRecord:
    """인쇄용 HTML을 PDF로 굳혀 보관하고 그 기록을 돌려준다."""
    resolved = config or get_settings()
    root = _archive_root(resolved)

    rendered = render_pdf(html)
    verify_korean_glyphs(rendered.content)

    stored = store_bytes(
        rendered.content,
        root=root,
        relative_path=build_relative_path(report_id, as_of=as_of),
    )
    record = ReportRecord(
        id=report_id,
        kind=kind,
        source_id=source_id,
        created_at=created_at,
        as_of=as_of,
        media_type=PDF_MEDIA_TYPE,
        byte_size=stored.byte_size,
        content_sha256=stored.content_sha256,
        storage_path=stored.relative_path,
        fully_verified=fully_verified,
        adopted_sections=tuple(adopted_sections),
        figures_only_sections=tuple(figures_only_sections),
        policy_sources=tuple(policy_sources),
        notes=tuple(notes),
    )

    try:
        database = engine or get_database_engine()
        with database.begin() as connection:
            insert_report(connection, record)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise ReportArchiveUnavailable(
            "보고서 메타데이터를 기록할 수 없습니다."
        ) from exc
    return record


def load_archived_pdf(
    report_id: UUID,
    *,
    config: Settings | None = None,
    engine: Engine | None = None,
) -> tuple[ReportRecord, bytes]:
    """보관된 문서와 그 기록을 함께 돌려준다.

    본문은 기록된 해시로 **검증해서** 읽는다. 손상된 파일을 원본인 척 내보내지
    않기 위해서다(``storage.load_bytes``).
    """
    resolved = config or get_settings()
    root = _archive_root(resolved)

    try:
        database = engine or get_database_engine()
        with database.connect() as connection:
            record = fetch_report(connection, report_id)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        raise ReportArchiveUnavailable("보고서 기록을 조회할 수 없습니다.") from exc

    if record is None:
        raise LookupError(f"보관된 보고서가 없습니다: {report_id}")

    content = load_bytes(
        root=root,
        relative_path=record.storage_path,
        expected_sha256=record.content_sha256,
    )
    return record, content


__all__ = [
    "PDF_MEDIA_TYPE",
    "ReportArchiveDisabled",
    "ReportArchiveUnavailable",
    "ReportStorageError",
    "PdfRenderingUnavailable",
    "archive_pdf_report",
    "load_archived_pdf",
]
