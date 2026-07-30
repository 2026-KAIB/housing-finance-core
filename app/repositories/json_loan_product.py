"""Validated loan-product provider for read-only DBeaver JSON exports."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.db.repositories.loan_product_repository import build_loan_candidates
from app.rule_engine.product_packs.handoff import ProductCandidate


class LoanProductSnapshotLoadError(ValueError):
    """Raised when a product snapshot cannot safely become engine candidates."""


class _LoanProductBaseRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(gt=0)
    fin_co_no: str
    kor_co_nm: str
    fin_prdt_nm: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    verified_at: date | None = None
    regulatory_review_no: str | None = None
    regulatory_review_date: date | None = None
    effective_start: date | None = None
    effective_end: date | None = None
    join_way: str | None = None
    join_deny: str | None = None
    join_member: str | None = None
    spcl_cnd: str | None = None
    etc_note: str | None = None
    category_code: str = Field(min_length=1)
    loan_lmt_raw: str | None = None
    loan_inci_expn: str | None = None
    erly_rpay_fee_raw: str | None = None
    dly_rate_raw: str | None = None

    @model_validator(mode="after")
    def validate_effective_period(self) -> "_LoanProductBaseRow":
        if (
            self.effective_start is not None
            and self.effective_end is not None
            and self.effective_start > self.effective_end
        ):
            raise ValueError("effective_start must not be later than effective_end")
        return self

    def covers(self, as_of: date) -> bool:
        if self.effective_start is not None and as_of < self.effective_start:
            return False
        return self.effective_end is None or as_of <= self.effective_end


class _LoanRateOptionRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: int = Field(gt=0)
    mrtg_type: str | None = None
    mrtg_type_nm: str | None = None
    rpay_type: str | None = None
    rpay_type_nm: str | None = None
    lend_rate_type: str | None = None
    lend_rate_type_nm: str | None = None
    lend_rate_min: Decimal | None = Field(default=None, ge=0)
    lend_rate_max: Decimal | None = Field(default=None, ge=0)
    lend_rate_avg: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_rate_range(self) -> "_LoanRateOptionRow":
        rates = (self.lend_rate_min, self.lend_rate_avg, self.lend_rate_max)
        if all(rate is not None for rate in rates):
            minimum, average, maximum = rates
            assert minimum is not None
            assert average is not None
            assert maximum is not None
            if not minimum <= average <= maximum:
                raise ValueError("loan rates must satisfy min <= avg <= max")
        return self


def _unwrap_dbeaver_rows(document: object, *, path: Path) -> list[dict[str, Any]]:
    rows: object
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict) and len(document) == 1:
        rows = next(iter(document.values()))
    else:
        raise LoanProductSnapshotLoadError(
            f"{path} must be a row array or a one-query DBeaver JSON export"
        )
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise LoanProductSnapshotLoadError(f"{path} does not contain a JSON row array")
    return rows


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoanProductSnapshotLoadError(
            f"failed to load loan-product snapshot from {path}: {exc}"
        ) from exc
    return _unwrap_dbeaver_rows(document, path=path)


class JsonLoanProductSnapshotRepository:
    """Convert two DBeaver result exports into the existing product contract."""

    def __init__(self, base_rows_path: str | Path, option_rows_path: str | Path) -> None:
        self.base_rows_path = Path(base_rows_path)
        self.option_rows_path = Path(option_rows_path)

    def load_candidates(self, *, as_of: date) -> tuple[ProductCandidate, ...]:
        try:
            base_rows = tuple(
                _LoanProductBaseRow.model_validate(row)
                for row in _read_rows(self.base_rows_path)
            )
            option_rows = tuple(
                _LoanRateOptionRow.model_validate(row)
                for row in _read_rows(self.option_rows_path)
            )
        except ValidationError as exc:
            raise LoanProductSnapshotLoadError(
                f"loan-product snapshot violates its row contract: {exc}"
            ) from exc

        product_ids = [row.id for row in base_rows]
        if len(product_ids) != len(set(product_ids)):
            raise LoanProductSnapshotLoadError("loan-product snapshot contains duplicate IDs")
        orphan_ids = {
            row.product_id for row in option_rows if row.product_id not in set(product_ids)
        }
        if orphan_ids:
            raise LoanProductSnapshotLoadError(
                f"loan-rate options reference unknown product IDs: {sorted(orphan_ids)}"
            )

        active_base_rows = tuple(row for row in base_rows if row.covers(as_of))
        active_ids = {row.id for row in active_base_rows}
        active_option_rows = tuple(
            row for row in option_rows if row.product_id in active_ids
        )
        return build_loan_candidates(
            [row.model_dump(mode="python") for row in active_base_rows],
            [row.model_dump(mode="python") for row in active_option_rows],
        )


__all__ = [
    "JsonLoanProductSnapshotRepository",
    "LoanProductSnapshotLoadError",
]
