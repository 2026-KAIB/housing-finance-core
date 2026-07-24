from collections.abc import Mapping
from datetime import date

from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.rules import (
    ComparisonOperator,
    ComparisonRule,
    PredicateRule,
)

# 이 파일은 실제 상품이 아니라 새 Pack 작성법을 보여주는 복사 전용 예시다.
# 실제 상품 파일은 상품 하나당 하나씩 만들고 영문 snake_case 파일명을 사용한다.
# 조건·실패 사유·적용기간·근거 URL을 공식 문서와 대조한 뒤에만 packs/__init__.py에 등록한다.
# 아래 숫자를 실제 KB 상품 조건으로 사용하거나 이 EXAMPLE_PRODUCT_PACK을 등록하면 안 된다.


def _income_or_employment_condition(facts: Mapping[str, object]) -> bool | None:
    income = facts.get("annual_income")
    employment_months = facts.get("employment_months")

    if isinstance(income, int | float) and income >= 30_000_000:
        return True
    if isinstance(employment_months, int) and employment_months >= 12:
        return True
    if income is not None and employment_months is not None:
        return False
    return None


EXAMPLE_PRODUCT_PACK = ProductRulePack(
    product_name="__개발예시 신용대출__",
    aliases=("__예시 신용대출__",),
    category=ProductCategory.CREDIT_LOAN,
    version="example-v1",
    effective_start_date=date(2026, 1, 1),
    effective_end_date=None,
    source_url="https://example.invalid/not-a-real-product",
    rules=(
        ComparisonRule(
            code="EXAMPLE_AGE",
            field_name="age",
            operator=ComparisonOperator.BETWEEN,
            expected=(19, 65),
            failure_reason="예시 연령 조건을 충족하지 않습니다.",
        ),
        PredicateRule(
            code="EXAMPLE_INCOME_OR_EMPLOYMENT",
            predicate=_income_or_employment_condition,
            failure_reason="예시 소득 또는 재직기간 조건을 충족하지 않습니다.",
            unknown_reason="소득 또는 재직기간 정보가 부족해 판정할 수 없습니다.",
        ),
    ),
)
