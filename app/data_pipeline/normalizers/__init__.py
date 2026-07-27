"""Source-to-domain normalization."""

from app.data_pipeline.normalizers.savings_product import (
    NormalizedSavingsOption,
    NormalizedSavingsProduct,
    SavingsOptionNormalizationIssue,
    normalize_savings_product,
)

__all__ = [
    "NormalizedSavingsOption",
    "NormalizedSavingsProduct",
    "SavingsOptionNormalizationIssue",
    "normalize_savings_product",
]
