"""예·적금 포트폴리오 엔진의 계층 간 입출력 계약.

목적:
    상품정책 Rule Pack과 옵션별 예·적금 평가가 끝난 후보를 실제 납입 계획으로
    바꿀 때, 일시예치금·월 납입액·정책값이 서로 섞이지 않게 한다.
기능:
    포트폴리오 후보, 서비스 배분정책, 예산, 배분 결과와 기관별 익스포저를
    불변 dataclass로 정의한다. 이 파일은 배분 알고리즘이나 DB 접근을 하지 않는다.
근거:
    공식 설계안 §12.1의 납입액·만기·예금자보호·상품 수 제약과 §25의
    기대수익·만기위험·유동성·기관집중도 목적함수를 표현한다. 역할분담 문서 §9.2의
    MVP 규칙 기반 최대 2~3개 상품 배분을 따른다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.engines.savings.models import (
    SavingsCalculationResult,
    SavingsEvaluationResult,
    SavingsProductKind,
)


class PortfolioAllocationBasis(StrEnum):
    """서로 더하면 안 되는 포트폴리오 예산 단위."""

    LUMP_SUM = "LUMP_SUM"
    MONTHLY = "MONTHLY"


class SavingsPortfolioStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INFEASIBLE = "INFEASIBLE"
    NO_ALLOCATION_REQUIRED = "NO_ALLOCATION_REQUIRED"


@dataclass(frozen=True)
class SavingsPortfolioCandidate:
    """평가가 끝난 상품 옵션 하나와 정책에서 확인된 납입 범위.

    ``minimum_allocation``과 ``maximum_allocation``은 예금이면 일시예치금, 적금이면
    월 납입액이다. ``maximum_allocation=None``은 확인된 무제한을 뜻하며, 미확인
    값을 뜻하지 않는다. 미확인 한도는 이 계약에 넣지 말고 앞 계층에서 UNKNOWN으로
    유지해야 한다.
    """

    candidate_id: str
    product_id: str
    institution_code: str
    institution_name: str
    source_version: str
    calculation: SavingsCalculationResult
    evaluation: SavingsEvaluationResult
    minimum_allocation: Decimal
    maximum_allocation: Decimal | None
    is_deposit_protected: bool

    def __post_init__(self) -> None:
        for field_name, value in (
            ("candidate_id", self.candidate_id),
            ("product_id", self.product_id),
            ("institution_code", self.institution_code),
            ("institution_name", self.institution_name),
            ("source_version", self.source_version),
        ):
            if not value.strip():
                raise ValueError(f"{field_name}은(는) 비어 있을 수 없습니다.")
        if self.minimum_allocation <= 0:
            raise ValueError("minimum_allocation은(는) 0보다 커야 합니다.")
        if (
            self.maximum_allocation is not None
            and self.maximum_allocation < self.minimum_allocation
        ):
            raise ValueError(
                "maximum_allocation은(는) minimum_allocation보다 작을 수 없습니다."
            )
        if self.calculation.product_name != self.evaluation.product_name:
            raise ValueError("계산 결과와 평가 결과의 상품명이 다릅니다.")
        if self.calculation.term_months != self.evaluation.term_months:
            raise ValueError("계산 결과와 평가 결과의 만기가 다릅니다.")
        if self.calculation.total_principal <= 0:
            raise ValueError("포트폴리오 환산 기준 원금은 0보다 커야 합니다.")

    @property
    def allocation_basis(self) -> PortfolioAllocationBasis:
        if self.calculation.product_kind is SavingsProductKind.TERM_DEPOSIT:
            return PortfolioAllocationBasis.LUMP_SUM
        return PortfolioAllocationBasis.MONTHLY


@dataclass(frozen=True)
class SavingsPortfolioPolicy:
    """서비스가 버전 관리해 호출 시 명시하는 포트폴리오 내부 정책.

    공식 문서는 위험 요소를 정의하지만 각 패널티의 수치는 정의하지 않는다.
    따라서 엔진에 숨은 상수를 두지 않고 가중치를 호출자가 명시한다.
    """

    max_products: int
    maturity_risk_weight: Decimal
    concentration_risk_weight: Decimal
    liquidity_shortfall_weight: Decimal
    allocation_tolerance: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        # 역할분담 문서 §9.2의 MVP 범위는 최대 2~3개다. 조합 폭증을 막기 위해
        # 이 구현은 3개까지만 허용하고, 그 이상은 향후 OR-Tools 계층으로 넘긴다.
        if self.max_products < 1 or self.max_products > 3:
            raise ValueError("MVP max_products은(는) 1 이상 3 이하여야 합니다.")
        for field_name, value in (
            ("maturity_risk_weight", self.maturity_risk_weight),
            ("concentration_risk_weight", self.concentration_risk_weight),
            ("liquidity_shortfall_weight", self.liquidity_shortfall_weight),
        ):
            if value < 0 or value > 1:
                raise ValueError(f"{field_name}은(는) 0 이상 1 이하이어야 합니다.")
        if self.allocation_tolerance < 0:
            raise ValueError("allocation_tolerance은(는) 음수일 수 없습니다.")


@dataclass(frozen=True)
class SavingsPortfolioInput:
    """포트폴리오 순수 함수가 소비하는 완전한 입력.

    ``monthly_savings_budget``은 적금의 월 납입 예산이고 ``lump_sum_budget``은
    예금에 한 번 넣을 현재 목돈이다. 단위가 다르므로 합산하거나 서로 전용하지 않는다.
    """

    candidates: tuple[SavingsPortfolioCandidate, ...]
    monthly_savings_budget: Decimal
    lump_sum_budget: Decimal
    existing_institution_deposits: Mapping[str, Decimal]
    deposit_protection_limit: Decimal
    policy: SavingsPortfolioPolicy

    def __post_init__(self) -> None:
        if self.monthly_savings_budget < 0:
            raise ValueError("monthly_savings_budget은(는) 음수일 수 없습니다.")
        if self.lump_sum_budget < 0:
            raise ValueError("lump_sum_budget은(는) 음수일 수 없습니다.")
        if self.deposit_protection_limit < 0:
            raise ValueError("deposit_protection_limit은(는) 음수일 수 없습니다.")
        for institution_code, amount in self.existing_institution_deposits.items():
            if not institution_code.strip():
                raise ValueError("금융회사 코드는 비어 있을 수 없습니다.")
            if amount < 0:
                raise ValueError("기존 금융회사별 예치액은 음수일 수 없습니다.")


@dataclass(frozen=True)
class SavingsPortfolioAllocation:
    candidate_id: str
    product_id: str
    product_name: str
    institution_code: str
    institution_name: str
    source_version: str
    product_kind: SavingsProductKind
    allocation_basis: PortfolioAllocationBasis
    allocation_amount: Decimal
    term_months: int
    maturity_date: date
    product_score: Decimal
    expected_total_principal: Decimal
    expected_maturity_amount: Decimal
    expected_net_interest: Decimal


@dataclass(frozen=True)
class InstitutionExposure:
    institution_code: str
    existing_deposit: Decimal
    new_maturity_amount: Decimal
    protected_new_maturity_amount: Decimal
    projected_total_exposure: Decimal
    protected_amount_for_limit: Decimal
    deposit_protection_limit: Decimal
    within_protection_limit: bool


@dataclass(frozen=True)
class PortfolioCandidateExclusion:
    candidate_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SavingsPortfolioResult:
    status: SavingsPortfolioStatus
    allocations: tuple[SavingsPortfolioAllocation, ...]
    monthly_allocated: Decimal
    monthly_unallocated: Decimal
    lump_sum_allocated: Decimal
    lump_sum_unallocated: Decimal
    coverage_ratio: Decimal
    expected_total_principal: Decimal
    expected_maturity_amount: Decimal
    expected_net_interest: Decimal
    weighted_product_score: Decimal | None
    expected_return_score: Decimal | None
    maturity_risk: Decimal | None
    concentration_risk: Decimal | None
    liquidity_shortfall: Decimal | None
    objective_score: Decimal | None
    institution_exposures: tuple[InstitutionExposure, ...] = field(default_factory=tuple)
    unselected_candidate_ids: tuple[str, ...] = field(default_factory=tuple)
    exclusions: tuple[PortfolioCandidateExclusion, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)
