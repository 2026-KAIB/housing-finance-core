from decimal import Decimal

from app.data_pipeline.normalizers.savings_product import normalize_savings_product
from app.engines.savings.models import InterestType, SavingsProductKind


def test_deposit_option_is_converted_from_percent_to_ratio() -> None:
    product = normalize_savings_product(
        {
            "fin_prdt_nm": "테스트 정기예금",
            "mtrt_int": "만기 후 1개월 이내 기본이율의 50%",
            "max_limit": Decimal("50000000"),
        },
        [
            {
                "fin_prdt_nm": "테스트 정기예금",
                "save_trm": 12,
                "rsrv_type": None,
                "rsrv_type_nm": None,
                "intr_rate_type": "S",
                "intr_rate_type_nm": "단리",
                "intr_rate": Decimal("3.20"),
                "intr_rate2": Decimal("3.80"),
            }
        ],
        product_kind=SavingsProductKind.TERM_DEPOSIT,
    )

    assert product.product_name == "테스트 정기예금"
    assert product.max_limit == Decimal("50000000")
    assert product.issues == ()
    assert product.options[0].term_months == 12
    assert product.options[0].interest_type is InterestType.SIMPLE
    assert product.options[0].annual_base_rate == Decimal("0.032")
    assert product.options[0].annual_max_rate == Decimal("0.038")


def test_installment_option_requires_reserve_type() -> None:
    product = normalize_savings_product(
        {"fin_prdt_nm": "테스트 적금"},
        [
            {
                "save_trm": 12,
                "intr_rate_type": "S",
                "intr_rate": Decimal("3.0"),
                "intr_rate2": Decimal("4.0"),
            }
        ],
        product_kind=SavingsProductKind.INSTALLMENT_SAVINGS,
    )

    assert product.options == ()
    assert product.issues[0].missing_or_invalid_fields == (
        "rsrv_type",
        "rsrv_type_nm",
    )


def test_invalid_option_is_reported_instead_of_becoming_zero_rate() -> None:
    product = normalize_savings_product(
        {"fin_prdt_nm": "테스트 정기예금"},
        [
            {
                "save_trm": 12,
                "intr_rate_type": "S",
                "intr_rate": "알 수 없음",
                "intr_rate2": Decimal("4.0"),
            }
        ],
        product_kind=SavingsProductKind.TERM_DEPOSIT,
    )

    assert product.options == ()
    assert product.issues[0].missing_or_invalid_fields == ("intr_rate",)
    assert "숫자" in product.issues[0].reason


def test_max_rate_below_base_rate_is_an_explicit_issue() -> None:
    product = normalize_savings_product(
        {"fin_prdt_nm": "테스트 정기예금"},
        [
            {
                "save_trm": 12,
                "intr_rate_type": "M",
                "intr_rate": Decimal("4.0"),
                "intr_rate2": Decimal("3.0"),
            }
        ],
        product_kind=SavingsProductKind.TERM_DEPOSIT,
    )

    assert product.options == ()
    assert product.issues[0].missing_or_invalid_fields == (
        "intr_rate",
        "intr_rate2",
    )


def test_nonstandard_extra_rate_information_is_preserved_but_not_invented_as_option() -> None:
    extra = {"unit_period_linked": [{"period": 1, "rate": 2.5}], "cd_linked": True}
    product = normalize_savings_product(
        {
            "fin_prdt_nm": "국민수퍼정기예금",
            "extra_rate_info": extra,
            "rate_beyond_contract_max": "최장기간 이후 별도 규정",
        },
        [],
        product_kind=SavingsProductKind.TERM_DEPOSIT,
    )

    assert product.extra_rate_info == extra
    assert product.options == ()
    assert product.rate_beyond_contract_max == "최장기간 이후 별도 규정"
