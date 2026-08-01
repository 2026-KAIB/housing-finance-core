"""대학생 페르소나 20명의 목표 계약을 고정한다.

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
    "persona_g_college_student_03_basic": ("11260", 262_500_000),
    "persona_h_college_student_04_basic": ("11350", 337_000_000),
    "persona_i_college_student_05_basic": ("11560", 300_000_000),
    "persona_j_college_student_06_basic": ("11440", 550_000_000),
    "persona_k_college_student_07_basic": ("11500", 365_000_000),
    "persona_l_college_student_08_affluent": ("11530", 233_000_000),
    "persona_m_college_student_09_affluent": ("11260", 262_500_000),
    "persona_n_college_student_10_affluent": ("11305", 260_000_000),
    "persona_o_college_student_11_affluent": ("11320", 285_000_000),
    "persona_p_college_student_12_affluent": ("11215", 259_500_000),
    "persona_q_college_student_13_affluent": ("11680", 370_000_000),
    "persona_r_college_student_14_poor": ("11350", 337_000_000),
    "persona_s_college_student_15_poor": ("11320", 285_000_000),
    "persona_t_college_student_16_poor": ("11230", 281_700_000),
    "persona_u_college_student_17_poor": ("11500", 365_000_000),
    "persona_v_college_student_18_poor": ("11200", 460_000_000),
    "persona_w_college_student_19_poor": ("11710", 660_000_000),
    "persona_x_college_student_20_poor": ("11620", 372_500_000),
}

RENT_KEYS = ("target_lease_deposit", "target_monthly_rent", "target_management_fee")

# 전환 이전 값. (월소득, 월평균지출, 월저축예산)
EXPECTED_FINANCES = {
    "persona_e_college_student_basic": (800_000, 700_000, 100_000),
    "persona_f_college_student_02_basic": (900_000, 700_000, 200_000),
    "persona_g_college_student_03_basic": (1_200_000, 900_000, 300_000),
    "persona_h_college_student_04_basic": (1_100_000, 850_000, 250_000),
    "persona_i_college_student_05_basic": (800_000, 750_000, 50_000),
    "persona_j_college_student_06_basic": (1_500_000, 1_100_000, 400_000),
    "persona_k_college_student_07_basic": (1_000_000, 900_000, 100_000),
    "persona_l_college_student_08_affluent": (2_000_000, 1_000_000, 1_000_000),
    "persona_m_college_student_09_affluent": (3_000_000, 1_200_000, 1_800_000),
    "persona_n_college_student_10_affluent": (4_000_000, 1_800_000, 2_200_000),
    "persona_o_college_student_11_affluent": (2_500_000, 1_500_000, 1_000_000),
    "persona_p_college_student_12_affluent": (1_800_000, 900_000, 900_000),
    "persona_q_college_student_13_affluent": (5_000_000, 2_000_000, 3_000_000),
    "persona_r_college_student_14_poor": (600_000, 550_000, 50_000),
    "persona_s_college_student_15_poor": (800_000, 650_000, 50_000),
    "persona_t_college_student_16_poor": (1_000_000, 950_000, 50_000),
    "persona_u_college_student_17_poor": (500_000, 520_000, 0),
    "persona_v_college_student_18_poor": (700_000, 700_000, 0),
    "persona_w_college_student_19_poor": (900_000, 800_000, 20_000),
    "persona_x_college_student_20_poor": (400_000, 600_000, 0),
}


def _personas():
    return [factory() for factory in (persona_e, *college_student_variant_factories())]


def test_all_twenty_college_students_are_generated():
    assert len(_personas()) == 20


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
    income, expense, savings = EXPECTED_FINANCES[persona["id"]]
    profile = persona["profile"]
    assert profile["monthly_income"] == income
    assert profile["monthly_average_expense"] == expense
    assert persona["savings_preferences"]["monthly_savings_budget"] == savings
