from decimal import Decimal

from app.data_pipeline.normalizers.loan_product import (
    normalize_loan_options,
    normalize_loan_product,
    parse_max_loan_amount,
)


def test_lend_rates_are_converted_from_percent_to_ratio() -> None:
    # optionList의 lend_rate_*는 퍼센트 숫자(5.2 = 연 5.2%)지만 formulas.py의
    # annual_rate는 비율(0.052)을 요구한다. 이 변환이 어댑터의 핵심 책임이다.
    options = normalize_loan_options(
        [
            {
                "fin_prdt_nm": "KB 주택담보대출",
                "mrtg_type_nm": "아파트/주택",
                "rpay_type_nm": "분할상환방식",
                "lend_rate_type_nm": "변동금리(금융채 5년)",
                "lend_rate_min": 5.2,
                "lend_rate_max": 6.6,
                "lend_rate_avg": 5.2,
            }
        ]
    )

    assert len(options) == 1
    assert options[0].annual_rate_min == Decimal("0.052")
    assert options[0].annual_rate_max == Decimal("0.066")
    assert options[0].annual_rate_avg == Decimal("0.052")


def test_option_without_complete_rates_is_skipped() -> None:
    # 금리를 확정할 수 없는 행을 0으로 채우면 상환액이 0이 된다 — 건너뛴다.
    options = normalize_loan_options(
        [
            {"fin_prdt_nm": "X", "lend_rate_min": 4.0, "lend_rate_max": 5.0},
            {
                "fin_prdt_nm": "X",
                "lend_rate_min": 4.0,
                "lend_rate_max": 5.0,
                "lend_rate_avg": 4.5,
            },
        ]
    )

    assert len(options) == 1
    assert options[0].annual_rate_avg == Decimal("0.045")


def test_rate_selection_picks_requested_bound() -> None:
    option = normalize_loan_options(
        [
            {
                "fin_prdt_nm": "X",
                "lend_rate_min": 4.0,
                "lend_rate_max": 6.0,
                "lend_rate_avg": 5.0,
            }
        ]
    )[0]

    assert option.rate("min") == Decimal("0.04")
    assert option.rate("avg") == Decimal("0.05")
    assert option.rate("max") == Decimal("0.06")


def test_single_max_amount_is_parsed() -> None:
    # 실제 원천 데이터(KB 비상금대출) — 23개 상품 중 유일하게 한도가 단일 숫자로
    # 확정되는 대출 상품이다.
    assert parse_max_loan_amount("최소 50만원 ~ 최대 300만원") == Decimal("3000000")
    assert parse_max_loan_amount("최소 1천만원 이상 최대 10억원 이내") == Decimal("1000000000")


def test_appraisal_dependent_limit_in_parentheses_is_not_parsed() -> None:
    # 실제 원천 데이터(KB스타 아파트담보대출). 본문이 "담보평가에 따른 대출가능금액"
    # 이고 숫자 한도는 괄호 안 부연이라, 10억원을 상품 한도로 확정하면 안 된다.
    loan_lmt = (
        "담보평가 및 소득금액 등에 따른 대출가능금액 이내 (최소 1천만원 이상 최대 10억원 이내)"
    )

    assert parse_max_loan_amount(loan_lmt) is None


def test_conditional_limits_in_parentheses_are_not_parsed() -> None:
    # 실제 원천 데이터(KB 신용대출). 괄호 안 조건부 한도를 상품 한도로 쓰면 안 된다.
    loan_lmt = (
        "최대 3.5억원 이내 (재직기간 1년미만 시 최대 1억원 이내, "
        "종합통장자동대출은 최대 1.5억원 이내)"
    )

    assert parse_max_loan_amount(loan_lmt) is None


def test_appraisal_dependent_limit_is_not_parsed() -> None:
    # 실제 원천 데이터(KB 주택담보대출). 본문 한도가 담보조사가격 의존이라
    # 괄호 안의 "최고 3억원"을 상품 한도로 오인하면 안 된다.
    loan_lmt = (
        "담보조사가격 및 소득금액, 담보물건지 지역 등에 따른 대출가능금액 이내 "
        "(통장자동대출 최고 3억원 이내)"
    )

    assert parse_max_loan_amount(loan_lmt) is None


def test_jeonse_limit_with_alternative_max_is_not_parsed() -> None:
    # 실제 원천 데이터(KB스타 전세자금대출 HUG).
    loan_lmt = (
        "최소 5백만원 이상 최대 4억원 (1주택 보유자는 최대 2억원) 이하 (임차보증금액의 80% 이내 등)"
    )

    assert parse_max_loan_amount(loan_lmt) is None


def test_missing_loan_lmt_is_none() -> None:
    assert parse_max_loan_amount(None) is None
    assert parse_max_loan_amount("") is None
    assert parse_max_loan_amount("담보조사가격에 따름") is None


def test_normalize_loan_product_combines_base_and_options() -> None:
    product = normalize_loan_product(
        {"fin_prdt_nm": "테스트대출", "loan_lmt": "최대 5억원 이내"},
        [
            {
                "fin_prdt_nm": "테스트대출",
                "rpay_type_nm": "분할상환방식",
                "lend_rate_min": 4.0,
                "lend_rate_max": 5.0,
                "lend_rate_avg": 4.5,
            }
        ],
    )

    assert product.product_name == "테스트대출"
    assert product.max_loan_amount == Decimal("500000000")
    assert len(product.options) == 1
    assert product.options[0].repayment_type_name == "분할상환방식"
