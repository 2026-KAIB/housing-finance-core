from contextlib import nullcontext
from datetime import date

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.services import loan_product_catalog
from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)


class _FakeEngine:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def connect(self) -> nullcontext[object]:
        return nullcontext(self.connection)


def test_database_provider_uses_the_existing_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Settings(_env_file=None).model_copy(
        update={"loan_product_provider": "database"}
    )
    connection = object()
    expected = ("candidate",)

    def fake_fetch(received: object, *, as_of: date) -> tuple[str, ...]:
        assert received is connection
        assert as_of == date(2026, 7, 31)
        return expected

    monkeypatch.setattr(
        loan_product_catalog,
        "fetch_loan_product_candidates",
        fake_fetch,
    )

    result = load_configured_loan_candidates(
        as_of=date(2026, 7, 31),
        config=config,
        engine=_FakeEngine(connection),  # type: ignore[arg-type]
    )

    assert result == expected


def test_database_failure_is_not_reported_as_an_empty_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Settings(_env_file=None).model_copy(
        update={"loan_product_provider": "database"}
    )

    def fail_fetch(received: object, *, as_of: date) -> tuple[()]:
        raise OperationalError("SELECT", {}, RuntimeError("database is down"))

    monkeypatch.setattr(
        loan_product_catalog,
        "fetch_loan_product_candidates",
        fail_fetch,
    )

    with pytest.raises(LoanProductCatalogUnavailable, match="database"):
        load_configured_loan_candidates(
            as_of=date(2026, 7, 31),
            config=config,
            engine=_FakeEngine(object()),  # type: ignore[arg-type]
        )
