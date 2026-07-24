from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Protocol

# 이 모듈은 DB 구조와 무관한 상품별 Rule Pack의 공용 입출력 계약이다.
# 새 상품을 추가할 때 이 모델을 수정하기보다 `packs/`에 ProductRulePack을 추가한다.
# 판정에 필요한 값은 `ProductEvaluationRequest.facts`에 이름-값 형태로 전달한다.
# 값이 없거나 해석할 수 없으면 FAIL로 단정하지 않고 UNKNOWN으로 반환해야 한다.


class ProductCategory(StrEnum):
    CREDIT_LOAN = "CREDIT_LOAN"
    JEONSE_LOAN = "JEONSE_LOAN"
    MORTGAGE_LOAN = "MORTGAGE_LOAN"
    TERM_DEPOSIT = "TERM_DEPOSIT"
    INSTALLMENT_SAVINGS = "INSTALLMENT_SAVINGS"


class EvaluationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProductEvaluationRequest:
    """상품명과 기준일, 판정에 필요한 정규화 값만 받는다."""

    product_name: str
    as_of: date
    facts: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductRuleDecision:
    rule_code: str
    status: EvaluationStatus
    reasons: tuple[str, ...] = field(default_factory=tuple)
    source_version: str | None = None


class ProductRule(Protocol):
    code: str

    def evaluate(
        self,
        request: ProductEvaluationRequest,
        *,
        source_version: str,
    ) -> ProductRuleDecision:
        """요청을 평가하고 PASS, FAIL 또는 UNKNOWN을 반환한다."""


@dataclass(frozen=True)
class ProductRulePack:
    """상품 하나의 특정 기간에 적용되는 검수 완료 규칙 묶음."""

    product_name: str
    category: ProductCategory
    version: str
    effective_start_date: date
    effective_end_date: date | None
    rules: tuple[ProductRule, ...]
    aliases: tuple[str, ...] = field(default_factory=tuple)
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not self.product_name.strip():
            raise ValueError("product_name은 비어 있을 수 없습니다.")
        if not self.version.strip():
            raise ValueError("version은 비어 있을 수 없습니다.")
        if not self.rules:
            raise ValueError("조건이 없는 상품은 자동 PASS를 막기 위해 등록할 수 없습니다.")
        if (
            self.effective_end_date is not None
            and self.effective_end_date < self.effective_start_date
        ):
            raise ValueError("effective_end_date는 effective_start_date보다 빠를 수 없습니다.")

    @property
    def source_version(self) -> str:
        return f"{self.product_name}@{self.version}"

    def is_active_on(self, as_of: date) -> bool:
        if as_of < self.effective_start_date:
            return False
        return self.effective_end_date is None or as_of <= self.effective_end_date


@dataclass(frozen=True)
class ProductEvaluationResult:
    requested_product_name: str
    product_name: str
    category: ProductCategory
    status: EvaluationStatus
    as_of: date
    pack_version: str
    decisions: tuple[ProductRuleDecision, ...]

    @property
    def eligible(self) -> bool:
        return self.status is EvaluationStatus.PASS

    @property
    def failed_decisions(self) -> tuple[ProductRuleDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status is EvaluationStatus.FAIL
        )

    @property
    def unknown_decisions(self) -> tuple[ProductRuleDecision, ...]:
        return tuple(
            decision
            for decision in self.decisions
            if decision.status is EvaluationStatus.UNKNOWN
        )
