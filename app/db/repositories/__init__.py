"""Persistence interfaces used by services and engines."""

from app.db.repositories.loan_product_repository import (
    build_loan_candidates,
    fetch_loan_product_candidates,
)
from app.db.repositories.savings_product_repository import (
    build_savings_candidates,
    fetch_savings_product_candidates,
)

__all__ = [
    "build_loan_candidates",
    "build_savings_candidates",
    "fetch_loan_product_candidates",
    "fetch_savings_product_candidates",
]
