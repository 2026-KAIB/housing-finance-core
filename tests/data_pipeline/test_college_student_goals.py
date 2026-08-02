"""대학생 페르소나 6명(기본·부유·가난 각 2명)의 목표 계약을 고정한다.

월세보증금에서 매매로 전환한 뒤, 전월세 필드가 되살아나거나 목표가가
조용히 바뀌는 것을 막는다. 목표가는 실거래 p05에서 온 값이라
'그럴듯한 숫자'로 대체되면 안 된다.
"""

import pytest

from app.data_pipeline.mydata.generate_all import (
    college_student_variant_factories,
    persona_e,
)

# 설계 문서 2.3의 표. 실거래 p05(전용 85m2 이하, 2025-01-01 이후), 2026-08-01 조회.
EXPECTED_GOALS = {
    "persona_e_college_student_basic": ("11650", 325_000_000),
    "persona_f_college_student_02_basic": ("11290", 390_000_000),
    "persona_l_college_student_08_affluent": ("11530", 233_000_000),
    "persona_m_college_student_09_affluent": ("11260", 262_500_000),
    "persona_r_college_student_14_poor": ("11350", 337_000_000),
    "persona_s_college_student_15_poor": ("11320", 285_000_000),
}

RENT_KEYS = ("target_lease_deposit", "target_monthly_rent", "target_management_fee")

# 전환 이전 값. (월소득, 월평균지출, 월저축예산, 유동자산 합계(current_assets),
# 월부채상환액(monthly_debt_payment))
#
# current_assets는 checking_balance + savings_balance + term_deposit_balance의
# 합이다(COLLEGE_STUDENT_VARIANT_SPECS). 이 두 필드를 검증하지 않으면 스펙의
# 잔액을 올려 모든 페르소나의 유동자산과 구매 가능성 판정을 바꿔도 이 테스트가
# 계속 통과한다 — 재무를 "손대지 않는다"는 설계 결정 4를 실제로는 지키지 못한다.
#
# persona_e_college_student_basic은 예외다. 손으로 작성한 유일한 페르소나라
# generate_all.py의 profile 리터럴에 current_assets/monthly_debt_payment 키 자체가
# 없다(계좌 잔액 1,000,000원은 generation_metadata.json의 provided_facts에만
# 있다). 있지도 않은 값을 여기서 지어내 박지 않는다 — None은 "0"이 아니라
# "이 테스트가 그 키의 부재를 확인한다"는 뜻이다.
EXPECTED_FINANCES = {
    "persona_e_college_student_basic": (800_000, 700_000, 100_000, None, None),
    "persona_f_college_student_02_basic": (900_000, 700_000, 200_000, 1_500_000, 0),
    "persona_l_college_student_08_affluent": (2_000_000, 1_000_000, 1_000_000, 25_000_000, 0),
    "persona_m_college_student_09_affluent": (3_000_000, 1_200_000, 1_800_000, 50_000_000, 0),
    "persona_r_college_student_14_poor": (600_000, 550_000, 50_000, 600_000, 0),
    "persona_s_college_student_15_poor": (800_000, 650_000, 50_000, 350_000, 100_000),
}


def _personas():
    return [factory() for factory in (persona_e, *college_student_variant_factories())]


def test_all_six_college_students_are_generated():
    assert len(_personas()) == 6


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_goal_is_home_purchase(persona):
    profile = persona["profile"]
    assert profile["target_housing_type"] == "purchase"


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_rent_fields_are_gone(persona):
    profile = persona["profile"]
    present = [key for key in RENT_KEYS if key in profile]
    assert present == [], f"전월세 필드가 남아 있습니다: {present}"


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_target_region_and_price_match_the_spec(persona):
    region, price = EXPECTED_GOALS[persona["id"]]
    profile = persona["profile"]
    assert profile["target_region"] == region
    assert profile["target_price"] == price
    # target_purchase_price가 Interfaces 계약상 정본이다. persona_e()는 이 값과
    # target_price를 서로 다른 리터럴로 각각 박아 두므로, 여기서 검증하지 않으면
    # 한쪽만 고치고 다른 쪽을 놓쳐도 테스트가 통과해 버린다.
    assert profile["target_purchase_price"] == price


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_finances_are_untouched(persona):
    """설계 결정 4 — 재무 값은 한 값도 바꾸지 않는다.

    전환 이전 값을 그대로 박아 둔다. 목표를 매매로 옮기면서 '이 소득으로는
    무리니 조금만 올리자'는 유혹이 생기는데, 그 시도는 두 번 다 비현실적인
    값으로 무너졌다(설계 2.2). 여기서 막는다.
    """
    income, expense, savings, current_assets, monthly_debt_payment = EXPECTED_FINANCES[
        persona["id"]
    ]
    profile = persona["profile"]
    assert profile["monthly_income"] == income
    assert profile["monthly_average_expense"] == expense
    assert persona["savings_preferences"]["monthly_savings_budget"] == savings

    # current_assets = checking_balance + savings_balance + term_deposit_balance.
    # 이 필드를 검증하지 않으면 세 잔액 스펙을 올려 유동자산과 구매 가능성 판정을
    # 통째로 바꿔도 이 테스트가 통과한다.
    if current_assets is None:
        assert "current_assets" not in profile, (
            f"{persona['id']}: current_assets 키가 새로 생겼습니다. "
            "손으로 작성한 예외였다면 이 테스트도 함께 갱신하세요."
        )
    else:
        assert profile["current_assets"] == current_assets

    if monthly_debt_payment is None:
        assert "monthly_debt_payment" not in profile, (
            f"{persona['id']}: monthly_debt_payment 키가 새로 생겼습니다. "
            "손으로 작성한 예외였다면 이 테스트도 함께 갱신하세요."
        )
    else:
        assert profile["monthly_debt_payment"] == monthly_debt_payment
