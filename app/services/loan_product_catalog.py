"""Resolve the configured temporary loan-product snapshot provider."""

from datetime import date
from pathlib import Path

from app.core.config import settings
from app.repositories import JsonLoanProductSnapshotRepository
from app.rule_engine.product_packs.handoff import ProductCandidate

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_configured_loan_candidates(
    *,
    as_of: date,
) -> tuple[ProductCandidate, ...]:
    """Load validated DB-export rows behind the same contract as direct SQL."""

    repository = JsonLoanProductSnapshotRepository(
        _resolve_project_path(settings.loan_product_base_json_path),
        _resolve_project_path(settings.loan_product_option_json_path),
    )
    return repository.load_candidates(as_of=as_of)


__all__ = ["load_configured_loan_candidates"]
