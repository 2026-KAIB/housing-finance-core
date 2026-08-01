"""Persistence interfaces used by services and engines."""

from app.db.repositories.loan_product_repository import (
    build_loan_candidates,
    fetch_loan_product_candidates,
)
from app.db.repositories.region_trade_repository import (
    build_region_trade_page,
    fetch_region_name,
    fetch_region_trade_count,
    fetch_region_trade_rows,
)
from app.db.repositories.savings_product_repository import (
    build_savings_candidates,
    fetch_savings_product_candidates,
)

__all__ = [
    "build_loan_candidates",
    "build_region_trade_page",
    "build_savings_candidates",
    "fetch_loan_product_candidates",
    "fetch_region_name",
    "fetch_region_trade_count",
    "fetch_region_trade_rows",
    "fetch_savings_product_candidates",
]
