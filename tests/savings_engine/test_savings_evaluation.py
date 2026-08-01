from datetime import date
from decimal import Decimal

from app.engines.savings.evaluation import add_months, evaluate_savings_option
from app.engines.savings.models import (
    InterestType,
    SavingsCalculationResult,
    SavingsEvaluationInput,
    SavingsEvaluationStatus,
    SavingsProductKind,
)

CALCULATION = SavingsCalculationResult(
    product_name="테스트 정기예금",
    product_kind=SavingsProductKind.TERM_DEPOSIT,
    term_months=12,
    interest_type=InterestType.SIMPLE,
    reserve_type_name=None,
    annual_base_rate=Decimal("0.03"),
    annual_max_rate=Decimal("0.05"),
    expected_annual_rate=Decimal("0.05"),
    bonus_achievement_probability=Decimal("0.8"),
    total_principal=Decimal("10000000"),
    gross_interest=Decimal("500000"),
    tax_amount=Decimal("77000"),
    net_interest=Decimal("423000"),
    maturity_amount=Decimal("10423000"),
    annualized_net_return_rate=Decimal("0.04"),
    net_return_rate=Decimal("0.0423"),
)


def _payload(**changes: object) -> SavingsEvaluationInput:
    values: dict[str, object] = {
        "calculation": CALCULATION,
        "as_of": date(2026, 7, 27),
        "fund_needed_date": date(2027, 7, 27),
        "maturity_tolerance_days": 180,
        "market_min_rate": Decimal("0.02"),
        "market_max_rate": Decimal("0.04"),
        "liquidity_score": Decimal("0.5"),
        "is_principal_protected": True,
        "accepts_principal_risk": False,
        "is_deposit_protected": True,
        "existing_institution_deposit": Decimal("0"),
        "deposit_protection_limit": Decimal("50000000"),
    }
    values.update(changes)
    return SavingsEvaluationInput(**values)  # type: ignore[arg-type]


def test_score_uses_documented_weights_after_hard_filters() -> None:
    result = evaluate_savings_option(_payload())

    assert result.status is SavingsEvaluationStatus.ELIGIBLE
    assert result.score == Decimal("88.000")
    assert result.components is not None
    assert result.components.maturity_fit_score == Decimal(1)


def test_maturity_after_fund_needed_date_is_filtered_before_scoring() -> None:
    result = evaluate_savings_option(
        _payload(fund_needed_date=date(2027, 6, 30))
    )

    assert result.status is SavingsEvaluationStatus.INELIGIBLE
    assert result.score is None
    assert "자금 필요시점" in result.reasons[0]


def test_exceeding_the_protection_limit_with_the_full_budget_is_not_ineligible() -> None:
    """전액이 한도를 넘는 것과 한 푼도 못 넣는 것은 다르다.

    기존 예치액 4,500만원에 한도가 5,000만원이면 500만원은 보호받으며 넣을 수
    있다. 여기서 상품을 버리면 "일부 가능"이 "전부 불가"로 뭉개진다 — 실제로
    목돈 1.5억 사용자에게 예금이 한 건도 추천되지 않았다. 상한 절단은 기관
    단위로 배분을 아는 포트폴리오 계층이 한다.
    """
    result = evaluate_savings_option(
        _payload(
            existing_institution_deposit=Decimal("45000000"),
            deposit_protection_limit=Decimal("50000000"),
        )
    )

    assert result.status is SavingsEvaluationStatus.ELIGIBLE
    # 전액을 넣었을 때의 예상 예치액은 사실대로 남는다. 판정 근거가 아니라
    # 배분 계층이 얼마를 잘라야 하는지 알려 주는 값이다.
    assert result.projected_institution_deposit == Decimal("55423000")


def test_a_full_institution_leaves_nothing_to_allocate() -> None:
    """기존 예치액만으로 한도가 찼으면 절단할 여지가 없다 — 그때는 부적격이다."""
    result = evaluate_savings_option(
        _payload(
            existing_institution_deposit=Decimal("50000000"),
            deposit_protection_limit=Decimal("50000000"),
        )
    )

    assert result.status is SavingsEvaluationStatus.INELIGIBLE
    assert result.score is None
    assert any("추가로 예치할 수 있는 금액이 없습니다" in reason for reason in result.reasons)


def test_an_unprotected_product_is_not_judged_by_the_protection_limit() -> None:
    result = evaluate_savings_option(
        _payload(
            is_deposit_protected=False,
            existing_institution_deposit=Decimal("50000000"),
            deposit_protection_limit=Decimal("50000000"),
        )
    )

    assert result.status is SavingsEvaluationStatus.ELIGIBLE


def test_add_months_clamps_month_end() -> None:
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
