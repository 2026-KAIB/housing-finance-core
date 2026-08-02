"""보고서를 PDF로 굳혀 보관하고 다시 꺼낸다.

흐름:
    인쇄용 HTML → PDF 렌더링 → 한글 글꼴 확인 → 본문 저장 → 기록 저장 → DB 색인

왜 순서가 이런가:
    기록을 먼저 쓰고 본문을 쓰면, 본문 쓰기가 실패했을 때 **가리키는 파일이 없는
    기록**이 남는다. 반대로 본문을 먼저 쓰고 기록 쓰기가 실패하면 주인 없는 파일이
    남는데, 그건 조회되지 않을 뿐 아무에게도 잘못된 답을 주지 않는다. 둘 중 덜
    위험한 쪽을 고른다.

왜 기록이 파일에 있는가:
    ``filesystem`` 공급원은 이름 그대로 파일시스템만으로 완결된다. 예전에는 본문만
    파일에 쓰고 기록은 Postgres 행으로 남겨서, DB에 닿지 못하면 **이미 만들어져
    디스크에 안전하게 저장된 문서**를 조회할 수 없었다. 색인 한 줄을 남기지
    못했다는 이유로 완성된 보고서를 버리는 셈이라, 기록을 본문 옆에 함께 둔다.

    DB 행은 그래서 이 저장소 안에서는 아무도 읽지 않는 **부차적 색인**이다.
    쓰지 못해도 문서는 그대로 조회되므로 보관을 실패로 만들지 않고 로그만 남긴다.
    대신 DB를 운영 색인으로 쓰는 배포라면 이 로그를 감시해야 한다 — 조용히 색인만
    빠진 상태가 될 수 있다.

왜 글꼴을 여기서 확인하는가:
    PDF는 폰트가 없어도 **성공적으로** 만들어진다. 글자만 빈 상자가 될 뿐이다.
    보관은 되돌리기 어려우므로, 읽을 수 없는 문서를 쌓기 전에 막는다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.repositories.report_repository import ReportRecord, insert_report
from app.db.session import DatabaseConfigurationError, get_database_engine
from app.reports.pdf import (
    PdfRenderingUnavailable,
    render_pdf,
    verify_korean_glyphs,
)
from app.reports.storage import (
    ReportStorageError,
    build_record_path,
    build_relative_path,
    load_bytes,
    read_if_present,
    store_bytes,
)

logger = logging.getLogger(__name__)

PDF_MEDIA_TYPE = "application/pdf"


class ReportArchiveDisabled(RuntimeError):
    """보관 기능이 꺼져 있다.

    **고장난 것이 아니다.** 공급원을 설정하지 않은 것과 설정한 공급원이 고장 난
    것을 가르기 위해 별도 예외로 둔다(예·적금 카탈로그와 같은 규약).
    """


def _encode_record(record: ReportRecord) -> bytes:
    """기록을 사람이 읽을 수 있는 JSON으로 굳힌다.

    ``ensure_ascii=False``는 정책 출처와 비고가 한국어라서다. 보관된 기록은 사후에
    사람이 열어 "이 문서는 언제 기준이며 무엇이 채택됐나"를 확인하는 용도다.
    """
    return json.dumps(
        {
            "id": str(record.id),
            "kind": record.kind,
            "source_id": str(record.source_id),
            "created_at": record.created_at.isoformat(),
            "as_of": record.as_of.isoformat(),
            "media_type": record.media_type,
            "byte_size": record.byte_size,
            "content_sha256": record.content_sha256,
            "storage_path": record.storage_path,
            "fully_verified": record.fully_verified,
            "adopted_sections": list(record.adopted_sections),
            "figures_only_sections": list(record.figures_only_sections),
            "policy_sources": list(record.policy_sources),
            "notes": list(record.notes),
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def _decode_record(raw: bytes) -> ReportRecord:
    """굳힌 기록을 되살린다. 읽을 수 없으면 **조용히 기본값으로 채우지 않는다.**

    항목이 빠지거나 형식이 깨진 기록으로 문서를 내보내면, 기준일이나 채택 내역이
    사실과 다른 문서가 나간다. 그래서 결측을 메우지 않고 저장소 오류로 올린다.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
        return ReportRecord(
            id=UUID(data["id"]),
            kind=data["kind"],
            source_id=UUID(data["source_id"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            as_of=date.fromisoformat(data["as_of"]),
            media_type=data["media_type"],
            byte_size=int(data["byte_size"]),
            content_sha256=data["content_sha256"],
            storage_path=data["storage_path"],
            fully_verified=bool(data["fully_verified"]),
            adopted_sections=tuple(data["adopted_sections"]),
            figures_only_sections=tuple(data["figures_only_sections"]),
            policy_sources=tuple(data["policy_sources"]),
            notes=tuple(data["notes"]),
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ReportStorageError(
            "보관된 기록의 형식이 올바르지 않습니다 — 손상되었을 수 있습니다."
        ) from exc


def _index_in_database(record: ReportRecord, engine: Engine | None) -> None:
    """DB에도 색인을 남긴다. 실패는 보관을 무르지 않고 로그로만 남긴다.

    예외 메시지를 로그에 싣지 않는 이유는 드라이버 오류에 접속 호스트·사용자명이
    섞여 나오기 때문이다. 예외 종류만으로도 "설정이 없다"와 "닿지 못했다"는 갈린다.
    """
    try:
        database = engine or get_database_engine()
        with database.begin() as connection:
            insert_report(connection, record)
    except (DatabaseConfigurationError, SQLAlchemyError) as exc:
        logger.error(
            "report %s archived to the filesystem but not indexed in the database (%s)",
            record.id,
            type(exc).__name__,
        )


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

    store_bytes(
        _encode_record(record),
        root=root,
        relative_path=build_record_path(report_id),
    )
    _index_in_database(record, engine)
    return record


def load_archived_pdf(
    report_id: UUID,
    *,
    config: Settings | None = None,
) -> tuple[ReportRecord, bytes]:
    """보관된 문서와 그 기록을 함께 돌려준다.

    본문은 기록된 해시로 **검증해서** 읽는다. 손상된 파일을 원본인 척 내보내지
    않기 위해서다(``storage.load_bytes``).
    """
    resolved = config or get_settings()
    root = _archive_root(resolved)

    raw = read_if_present(root=root, relative_path=build_record_path(report_id))
    if raw is None:
        raise LookupError(f"보관된 보고서가 없습니다: {report_id}")
    record = _decode_record(raw)

    content = load_bytes(
        root=root,
        relative_path=record.storage_path,
        expected_sha256=record.content_sha256,
    )
    return record, content


__all__ = [
    "PDF_MEDIA_TYPE",
    "ReportArchiveDisabled",
    "ReportStorageError",
    "PdfRenderingUnavailable",
    "archive_pdf_report",
    "load_archived_pdf",
]
