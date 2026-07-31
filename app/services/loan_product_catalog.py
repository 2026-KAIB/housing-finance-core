"""Resolve the configured loan-product provider behind one engine contract."""

from datetime import date
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.repositories import fetch_loan_product_candidates
from app.db.session import DatabaseConfigurationError, get_database_engine
from app.repositories import (
    JsonLoanProductSnapshotRepository,
    LoanProductSnapshotLoadError,
)
from app.rule_engine.product_packs.handoff import ProductCandidate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LoanProductCatalogUnavailable(RuntimeError):
    """Raised when the selected provider cannot supply trustworthy candidates."""


def _resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_configured_loan_candidates(
    *,
    as_of: date,
    config: Settings | None = None,
    engine: Engine | None = None,
) -> tuple[ProductCandidate, ...]:
    """Load candidates from JSON or PostgreSQL without changing engine inputs."""

    resolved = config or get_settings()
    if resolved.loan_product_provider == "database":
        try:
            database_engine = engine or get_database_engine()
            with database_engine.connect() as connection:
                return fetch_loan_product_candidates(connection, as_of=as_of)
        except (DatabaseConfigurationError, SQLAlchemyError) as exc:
            raise LoanProductCatalogUnavailable(
                "the configured database loan-product provider is unavailable"
            ) from exc

    try:
        repository = JsonLoanProductSnapshotRepository(
            _resolve_project_path(resolved.loan_product_base_json_path),
            _resolve_project_path(resolved.loan_product_option_json_path),
        )
        return repository.load_candidates(as_of=as_of)
    except LoanProductSnapshotLoadError as exc:
        raise LoanProductCatalogUnavailable(
            "the configured JSON loan-product provider is unavailable"
        ) from exc


__all__ = [
    "LoanProductCatalogUnavailable",
    "load_configured_loan_candidates",
]
