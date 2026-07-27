from datetime import date
from decimal import Decimal

from app.data_pipeline.normalizers.savings_product import normalize_savings_product
from app.db.repositories.savings_product_repository import build_savings_candidates
from app.engines.savings.models import SavingsProductKind

BASE_ROWS = [
    {
        "id": 1,
        "fin_co_no": "0010927",
        "kor_co_nm": "국민은행",
        "fin_prdt_nm": "테스트 정기예금",
        "source_type": "api",
        "verified_at": date(2026, 7, 27),
        "dcls_month": "202607",
        "dcls_strt_day": date(2026, 7, 1),
        "dcls_end_day": None,
        "fin_co_subm_day": None,
        "regulatory_review_no": None,
        "regulatory_review_date": None,
        "effective_start": None,
        "effective_end": None,
        "join_way": "스마트폰",
        "join_deny": "1",
        "join_member": "실명의 개인",
        "spcl_cnd": "우대조건",
        "etc_note": None,
        "category_code": "deposit",
        "mtrt_int": "만기 후 이율",
        "max_limit": Decimal("50000000"),
        "rate_beyond_contract_max": None,
        "extra_rate_info": None,
    },
    {
        "id": 2,
        "fin_co_no": "0010927",
        "kor_co_nm": "국민은행",
        "fin_prdt_nm": "테스트 적금",
        "source_type": "manual_pdf",
        "verified_at": date(2026, 7, 27),
        "dcls_month": None,
        "dcls_strt_day": None,
        "dcls_end_day": None,
        "fin_co_subm_day": None,
        "regulatory_review_no": "심의필-1",
        "regulatory_review_date": date(2026, 7, 1),
        "effective_start": date(2026, 7, 1),
        "effective_end": date(2027, 6, 30),
        "join_way": "영업점",
        "join_deny": None,
        "join_member": "실명의 개인",
        "spcl_cnd": None,
        "etc_note": None,
        "category_code": "saving",
        "mtrt_int": "만기 후 이율",
        "max_limit": None,
        "rate_beyond_contract_max": None,
        "extra_rate_info": None,
    },
]

OPTION_ROWS = [
    {
        "product_id": 1,
        "save_trm": 12,
        "rsrv_type": None,
        "rsrv_type_nm": None,
        "intr_rate_type": "S",
        "intr_rate_type_nm": "단리",
        "intr_rate": Decimal("3.00"),
        "intr_rate2": Decimal("3.50"),
    },
    {
        "product_id": 2,
        "save_trm": 24,
        "rsrv_type": "F",
        "rsrv_type_nm": "자유적립식",
        "intr_rate_type": "S",
        "intr_rate_type_nm": "단리",
        "intr_rate": Decimal("3.20"),
        "intr_rate2": Decimal("4.20"),
    },
]


def test_options_are_grouped_without_leaking_product_id() -> None:
    candidates = build_savings_candidates(BASE_ROWS, OPTION_ROWS)

    assert len(candidates) == 2
    assert candidates[0].base_data["product_id"] == 1
    assert candidates[0].option_list[0]["fin_prdt_nm"] == "테스트 정기예금"
    assert "product_id" not in candidates[0].option_list[0]
    assert candidates[1].option_list[0]["rsrv_type_nm"] == "자유적립식"


def test_product_without_options_is_not_silently_removed() -> None:
    candidates = build_savings_candidates(BASE_ROWS, [])

    assert len(candidates) == 2
    assert all(candidate.option_list == () for candidate in candidates)


def test_repository_output_feeds_savings_normalizer_without_remapping() -> None:
    candidates = build_savings_candidates(BASE_ROWS, OPTION_ROWS)

    deposit = normalize_savings_product(
        candidates[0].base_data,
        candidates[0].option_list,
        product_kind=SavingsProductKind.TERM_DEPOSIT,
    )
    savings = normalize_savings_product(
        candidates[1].base_data,
        candidates[1].option_list,
        product_kind=SavingsProductKind.INSTALLMENT_SAVINGS,
    )

    assert deposit.options[0].annual_base_rate == Decimal("0.03")
    assert savings.options[0].term_months == 24
    assert savings.options[0].reserve_type == "F"
