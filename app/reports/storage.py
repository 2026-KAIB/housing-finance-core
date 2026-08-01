"""보고서 파일 본문의 저장소.

DB에는 메타데이터만 두고 본문은 여기 둔다(``db/models/report.py`` 참고).

경로를 여기서만 만드는 이유:
    보관 경로는 사용자에게서 온 값으로 조립되면 안 된다. 파일명이 입력에서 오면
    ``../``로 저장소 밖을 쓸 수 있다. 그래서 경로는 **서버가 만든 UUID**로만
    구성하고, 읽을 때도 저장된 상대 경로가 루트 안에 있는지 다시 확인한다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID


class ReportStorageError(RuntimeError):
    """보관 위치를 쓸 수 없거나 저장된 파일을 신뢰할 수 없다."""


@dataclass(frozen=True)
class StoredFile:
    relative_path: str
    content_sha256: str
    byte_size: int


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _resolved_root(root: Path) -> Path:
    return root.expanduser().resolve()


def build_relative_path(report_id: UUID, *, as_of: date, suffix: str = ".pdf") -> str:
    """``2026/08/<uuid>.pdf``.

    날짜로 나누는 것은 한 디렉터리에 파일이 무한정 쌓이지 않게 하려는 것이고,
    파일명이 UUID인 것은 이름에서 개인정보나 매물 식별자가 새지 않게 하려는 것이다.
    """
    return f"{as_of.year:04d}/{as_of.month:02d}/{report_id}{suffix}"


def store_bytes(content: bytes, *, root: Path, relative_path: str) -> StoredFile:
    """본문을 저장소에 쓰고 그 사실을 돌려준다."""
    if not content:
        raise ReportStorageError("빈 내용을 보관하지 않습니다.")

    base = _resolved_root(root)
    target = (base / relative_path).resolve()
    if not target.is_relative_to(base):
        raise ReportStorageError("보관 경로가 저장소 루트를 벗어납니다.")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 같은 id로 두 번 쓰는 것은 덮어쓰기가 아니라 오류다. 보관된 문서는
        # 사후에 바뀌면 안 된다 — 바뀌면 이미 전달한 문서와 내용이 갈린다.
        with target.open("xb") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise ReportStorageError("같은 식별자의 문서가 이미 보관되어 있습니다.") from exc
    except OSError as exc:
        raise ReportStorageError("보관 위치에 쓸 수 없습니다.") from exc

    return StoredFile(
        relative_path=relative_path,
        content_sha256=content_digest(content),
        byte_size=len(content),
    )


def load_bytes(*, root: Path, relative_path: str, expected_sha256: str | None = None) -> bytes:
    """보관된 본문을 읽는다. 해시를 알면 **읽은 것이 그것인지 확인한다.**

    디스크 손상이나 저장소 교체로 내용이 달라진 파일을 그대로 내보내면, 사용자는
    문서번호는 같은데 내용이 다른 문서를 받는다. 확인 실패는 조용히 지나가지 않는다.
    """
    base = _resolved_root(root)
    target = (base / relative_path).resolve()
    if not target.is_relative_to(base):
        raise ReportStorageError("보관 경로가 저장소 루트를 벗어납니다.")

    try:
        content = target.read_bytes()
    except FileNotFoundError as exc:
        raise ReportStorageError("보관된 문서를 찾을 수 없습니다.") from exc
    except OSError as exc:
        raise ReportStorageError("보관된 문서를 읽을 수 없습니다.") from exc

    if expected_sha256 is not None and content_digest(content) != expected_sha256:
        raise ReportStorageError(
            "보관된 문서의 내용이 기록된 해시와 다릅니다 — 손상되었을 수 있습니다."
        )
    return content


__all__ = [
    "ReportStorageError",
    "StoredFile",
    "build_relative_path",
    "content_digest",
    "load_bytes",
    "store_bytes",
]
