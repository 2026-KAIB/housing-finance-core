"""외부 AI로 나가기 전 키 단위 차단.

이 게이트는 **무료 등급 Gemini로 나가는 마지막 문 앞**에 있다. Google 약관은
제출한 프롬프트를 검토·학습에 쓸 수 있다고 명시하므로 한 번 나간 값은 되돌릴 수
없다. 그래서 여기서는 "지금 아는 이름을 다 적었나"가 아니라 **이름이 조금 달라져도
막히나**를 검증한다.

값 단위 검사는 별도 계층(`ai_explanation/egress.py`)이 맡는다. 두 층은 서로
대체하지 않는다 — 이름은 낯설고 값도 패턴에 안 맞는 개인정보가 있기 때문이다.
"""

import pytest

from app.reports.context import sanitize_report_facts


@pytest.mark.parametrize(
    "key",
    [
        # 정확일치 목록이 이미 담당하던 것
        "account_num",
        "birth_date",
        "resident_registration_number",
        "access_token",
        "transaction_list",
        # 이름만 조금 다른 같은 계열 — 예전에는 그대로 통과했다
        "birth_year",
        "birthday",
        "account_holder_name",
        "repay_account_num",
        "deposit_account_no",
        "mobile_phone",
        "user_email_address",
        "api_key_value",
        "refresh_token_expires_at",
        "card_number_masked",
        "raw_transaction_history",
        "passport_number",
        "driver_license_no",
    ],
)
def test_identifier_families_are_dropped_whatever_the_exact_name(key: str) -> None:
    """새 필드가 생길 때마다 목록에 추가하는 것을 잊지 않기를 기대하지 않는다."""
    assert sanitize_report_facts({key: "값", "monthly_surplus": "100000"}) == {
        "monthly_surplus": "100000"
    }


def test_birth_year_was_the_real_hole() -> None:
    """``birth_date``는 막히는데 ``birth_year``는 통과했다. 페르소나가 그 키를 쓴다."""
    cleaned = sanitize_report_facts({"birth_year": 2000, "age": 26})

    assert cleaned == {"age": 26}


@pytest.mark.parametrize(
    "key",
    [
        # 매물 소재지는 보고서의 정상 표시 항목이고 서술 검증도 이 값을 쓴다.
        # `address`를 계열로 넓히면 매물 보고서가 조용히 비어버린다.
        "address_summary",
        # 아래는 계산 결과다. 넓힌 차단이 여기까지 먹으면 보고서가 망가진다.
        "monthly_surplus",
        "expected_maturity_amount",
        "product_name",
        "funding_shortfall",
        "coverage_ratio",
        "total_financial_cost",
        "annual_rate",
        "region_code",
        "as_of",
    ],
)
def test_report_facts_that_must_survive(key: str) -> None:
    """차단을 넓힌 것이 필요한 값까지 지우지 않는지 확인한다.

    이게 없으면 위 검사들은 "전부 지우기"로도 통과한다.
    """
    assert sanitize_report_facts({key: "값"}) == {key: "값"}


def test_nested_structures_are_cleaned_at_every_depth() -> None:
    payload = {
        "sections": {
            "loan": {
                "birth_year": 1990,
                "plans": [
                    {"account_number": "110-234-567890", "amount": "1000"},
                    {"amount": "2000"},
                ],
            }
        }
    }

    assert sanitize_report_facts(payload) == {
        "sections": {"loan": {"plans": [{"amount": "1000"}, {"amount": "2000"}]}}
    }


def test_key_matching_ignores_case_and_surrounding_space() -> None:
    assert sanitize_report_facts({" Birth_Year ": 1990, "age": 26}) == {"age": 26}
