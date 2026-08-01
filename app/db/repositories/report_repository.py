"""보관된 보고서 메타데이터의 I/O.

이 계층은 행을 넣고 빼는 것만 한다. 무엇을 보관할지, 파일을 어디에 쓸지는
``services/report_archive.py``가 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.db.models.report import reports_table


@dataclass(frozen=True)
class ReportRecord:
    id: UUID
    kind: str
    source_id: UUID
    created_at: datetime
    as_of: date
    media_type: str
    byte_size: int
    content_sha256: str
    storage_path: str
    fully_verified: bool
    adopted_sections: tuple[str, ...]
    figures_only_sections: tuple[str, ...]
    policy_sources: tuple[str, ...]
    notes: tuple[str, ...]


def _row_to_record(row) -> ReportRecord:
    return ReportRecord(
        id=row.id if isinstance(row.id, UUID) else UUID(str(row.id)),
        kind=row.kind,
        source_id=(
            row.source_id if isinstance(row.source_id, UUID) else UUID(str(row.source_id))
        ),
        created_at=row.created_at,
        as_of=row.as_of,
        media_type=row.media_type,
        byte_size=row.byte_size,
        content_sha256=row.content_sha256,
        storage_path=row.storage_path,
        fully_verified=bool(row.fully_verified),
        adopted_sections=tuple(row.adopted_sections or ()),
        figures_only_sections=tuple(row.figures_only_sections or ()),
        policy_sources=tuple(row.policy_sources or ()),
        notes=tuple(row.notes or ()),
    )


def insert_report(connection: Connection, record: ReportRecord) -> None:
    connection.execute(
        reports_table.insert().values(
            id=record.id,
            kind=record.kind,
            source_id=record.source_id,
            created_at=record.created_at,
            as_of=record.as_of,
            media_type=record.media_type,
            byte_size=record.byte_size,
            content_sha256=record.content_sha256,
            storage_path=record.storage_path,
            fully_verified=record.fully_verified,
            adopted_sections=list(record.adopted_sections),
            figures_only_sections=list(record.figures_only_sections),
            policy_sources=list(record.policy_sources),
            notes=list(record.notes),
        )
    )


def fetch_report(connection: Connection, report_id: UUID) -> ReportRecord | None:
    row = connection.execute(
        select(reports_table).where(reports_table.c.id == report_id)
    ).one_or_none()
    return None if row is None else _row_to_record(row)


__all__ = ["ReportRecord", "fetch_report", "insert_report"]
