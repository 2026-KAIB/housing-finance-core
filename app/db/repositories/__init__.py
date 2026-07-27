"""Persistence interfaces used by services and engines."""

from app.db.repositories.savings_product_repository import (
    build_savings_candidates,
    fetch_savings_product_candidates,
)

__all__ = [
    "build_savings_candidates",
    "fetch_savings_product_candidates",
]
