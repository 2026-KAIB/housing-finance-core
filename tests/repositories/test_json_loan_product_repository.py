import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.repositories import (
    JsonLoanProductSnapshotRepository,
    LoanProductSnapshotLoadError,
)

_ROOT = Path(__file__).resolve().parents[2]
_BASE_ROWS = (
    _ROOT / "sample_data" / "loan_products" / "loan_base_rows_2026-07-31.json"
)
_OPTION_ROWS = (
    _ROOT / "sample_data" / "loan_products" / "loan_option_rows_2026-07-31.json"
)


def _repository() -> JsonLoanProductSnapshotRepository:
    return JsonLoanProductSnapshotRepository(_BASE_ROWS, _OPTION_ROWS)


def test_dbeaver_exports_build_all_database_candidates() -> None:
    candidates = _repository().load_candidates(as_of=date(2026, 7, 31))

    assert len(candidates) == 9
    assert sum(len(candidate.option_list) for candidate in candidates) == 31
    mortgage = next(
        candidate
        for candidate in candidates
        if candidate.product_name == "KB 주택담보대출"
    )
    assert mortgage.base_data["product_id"] == 19
    assert mortgage.base_data["category_code"] == "mortgage"
    assert mortgage.base_data["loan_lmt"].startswith("담보조사가격")
    assert mortgage.option_list[0]["lend_rate_avg"] == Decimal("5.20")


def test_snapshot_filters_products_outside_their_effective_period() -> None:
    candidates = _repository().load_candidates(as_of=date(2030, 1, 1))

    assert candidates == ()


def test_repository_rejects_an_orphan_rate_option(tmp_path: Path) -> None:
    base_path = tmp_path / "base.json"
    option_path = tmp_path / "options.json"
    base_path.write_text(_BASE_ROWS.read_text(encoding="utf-8"), encoding="utf-8")
    option_path.write_text(
        json.dumps(
            {
                "query": [
                    {
                        "product_id": 999999,
                        "mrtg_type": None,
                        "mrtg_type_nm": None,
                        "rpay_type": None,
                        "rpay_type_nm": None,
                        "lend_rate_type": None,
                        "lend_rate_type_nm": None,
                        "lend_rate_min": "4.0",
                        "lend_rate_max": "5.0",
                        "lend_rate_avg": "4.5",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LoanProductSnapshotLoadError, match="unknown product IDs"):
        JsonLoanProductSnapshotRepository(
            base_path,
            option_path,
        ).load_candidates(as_of=date(2026, 7, 31))


def test_repository_rejects_an_unsupported_json_envelope(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"first": [], "second": []}', encoding="utf-8")

    with pytest.raises(LoanProductSnapshotLoadError, match="DBeaver"):
        JsonLoanProductSnapshotRepository(
            invalid,
            _OPTION_ROWS,
        ).load_candidates(as_of=date(2026, 7, 31))
