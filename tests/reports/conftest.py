"""보고서 테스트가 공유하는 계산 결과 픽스처.

실제 파이프라인(규제 해석 → 자격 판정 → 계산 → 종합추천 → 스트레스)을 한 번 돌려
``ReportAIInput``을 만든다. 네트워크는 쓰지 않는다 — AI 호출은 각 테스트가 가짜
생성기를 주입한다.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.regulations.mortgage_limits import HousingStatus
from app.reports.context import build_report_ai_input
from app.rule_engine.product_packs.handoff import ProductCandidate
from app.rule_engine.product_packs.models import ProductCategory, ProductRulePack
from app.rule_engine.product_packs.registry import ProductRulePackRegistry
from app.rule_engine.product_packs.rules import ComparisonOperator, ComparisonRule
from app.schemas.report import ReportAIInput
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SimulationInput,
    SimulationResult,
    UserProfile,
)
from app.services.simulation_orchestrator import run_simulation

REPORT_AS_OF = date(2026, 7, 28)
REPORT_CALCULATED_AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
REPORT_SIMULATION_ID = UUID("0f9b21e4-4c1a-4d7f-9c3e-2b6a5d8e1f30")
MORTGAGE_PRODUCT = "KB 주택담보대출"
# 이 조건에서 계산되는 대출 가능액. 표시 반올림을 확인하는 테스트가 참조한다.
EXPECTED_AMOUNT_LABEL = "283,520,507원"


def _simulation_input() -> SimulationInput:
    return SimulationInput(
        profile=UserProfile(age=34, annual_income=Decimal("60000000"), is_first_home_buyer=True),
        housing_goal=HousingGoal(
            target_amount=Decimal("500000000"),
            target_date=date(2028, 7, 30),
            region_code="11680",
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal("5000000"),
            monthly_expense=Decimal("2000000"),
            liquid_assets=Decimal("150000000"),
            monthly_debt_payment=Decimal("300000"),
        ),
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal("1800000"),
        ),
    )


def _pack() -> ProductRulePack:
    return ProductRulePack(
        product_name=MORTGAGE_PRODUCT,
        category=ProductCategory.MORTGAGE_LOAN,
        version="test-1",
        effective_start_date=date(2026, 1, 1),
        effective_end_date=None,
        rules=(
            ComparisonRule(
                code="TEST_MIN_AGE",
                field_name="age",
                operator=ComparisonOperator.GTE,
                expected=19,
                failure_reason="미성년자는 신청할 수 없습니다.",
            ),
        ),
    )


def _candidate() -> ProductCandidate:
    return ProductCandidate(
        product_name=MORTGAGE_PRODUCT,
        base_data={
            "source_type": "manual_pdf",
            "fin_prdt_nm": MORTGAGE_PRODUCT,
            "loan_lmt": "담보조사가격 및 소득금액에 따른 대출가능금액 이내",
            "spcl_cnd": "최고 연 1.4%p 우대\n- 실적 연동 우대: 최고 연 0.9%p",
            "erly_rpay_fee": "중도상환원금 × 수수료율(0.55%)",
        },
        option_list=(
            {
                "fin_prdt_nm": MORTGAGE_PRODUCT,
                "mrtg_type_nm": "아파트",
                "rpay_type_nm": "분할상환방식",
                "lend_rate_type_nm": "변동금리",
                "lend_rate_min": 3.0,
                "lend_rate_max": 3.0,
                "lend_rate_avg": 3.0,
            },
        ),
    )


@pytest.fixture(scope="session")
def simulation() -> SimulationResult:
    """전 구간 계산 결과. 화면 렌더러는 4갈래 분류를 쓰므로 이쪽을 받는다."""
    return run_simulation(
        _simulation_input(),
        simulation_id=REPORT_SIMULATION_ID,
        as_of=REPORT_AS_OF,
        calculated_at=REPORT_CALCULATED_AT,
        loan_candidates=[_candidate()],
        registry=ProductRulePackRegistry((_pack(),)),
    )


@pytest.fixture(scope="session")
def report_input(simulation: SimulationResult) -> ReportAIInput:
    """AI에 보내는 허용목록 입력."""
    return build_report_ai_input(simulation)


@pytest.fixture(scope="session")
def product_terms() -> dict[str, dict[str, str]]:
    """표시 전용 상품 조건. 렌더러 테스트가 쓴다."""
    base = _candidate().base_data
    return {
        MORTGAGE_PRODUCT: {
            "spcl_cnd": str(base["spcl_cnd"]),
            "erly_rpay_fee": str(base["erly_rpay_fee"]),
        }
    }
