from datetime import date
from decimal import Decimal

from app.data_pipeline.normalizers.loan_product import normalize_loan_product
from app.db.repositories.loan_product_repository import build_loan_candidates

# 실제 DB(mydb, 2026-07-27 조회)의 행 형태를 그대로 옮긴 픽스처.
BASE_ROWS = [
    {
        "id": 25,
        "fin_co_no": "0010927",
        "kor_co_nm": "국민은행",
        "fin_prdt_nm": "KB 신용대출",
        "source_type": "manual_pdf",
        "verified_at": date(2026, 7, 23),
        "regulatory_review_no": "준법감시인 심의필 제2026-1234-5호",
        "regulatory_review_date": date(2026, 1, 1),
        "effective_start": date(2026, 1, 1),
        "effective_end": date(2027, 11, 30),
        "join_way": "영업점, 인터넷, 스마트폰",
        "join_deny": "1",
        "join_member": "실명의 개인",
        "spcl_cnd": None,
        "etc_note": None,
        "category_code": "credit_loan",
        "loan_lmt_raw": "최대 3.5억원 이내 (재직기간 1년미만 시 최대 1억원 이내)",
        "loan_inci_expn": "인지세",
        "erly_rpay_fee_raw": "중도상환금액×0.55%×(잔여일수÷3년)",
        "dly_rate_raw": "대출이자율+연3%(최고 연15%)",
    },
    {
        "id": 27,
        "fin_co_no": "0010927",
        "kor_co_nm": "국민은행",
        "fin_prdt_nm": "KB 비상금대출",
        "source_type": "manual_pdf",
        "verified_at": date(2026, 7, 23),
        "regulatory_review_no": "준법감시인 심의필 제2024-9999-9호",
        "regulatory_review_date": date(2024, 10, 17),
        "effective_start": date(2024, 10, 17),
        "effective_end": date(2026, 9, 30),
        "join_way": "스마트폰",
        "join_deny": "1",
        "join_member": "실명의 개인",
        "spcl_cnd": None,
        "etc_note": None,
        "category_code": "credit_loan",
        "loan_lmt_raw": "최소 50만원 ~ 최대 300만원",
        "loan_inci_expn": None,
        "erly_rpay_fee_raw": None,
        "dly_rate_raw": None,
    },
]

OPTION_ROWS = [
    {
        "product_id": 25,
        "mrtg_type": "N",
        "mrtg_type_nm": "무보증신용",
        "rpay_type": "S",
        "rpay_type_nm": "일시상환/분할상환",
        "lend_rate_type": "C",
        "lend_rate_type_nm": "변동금리(CD 91일물)",
        "lend_rate_min": Decimal("4.13"),
        "lend_rate_max": Decimal("5.13"),
        "lend_rate_avg": Decimal("4.13"),
    },
    {
        "product_id": 27,
        "mrtg_type": "N",
        "mrtg_type_nm": "무보증신용",
        "rpay_type": "M",
        "rpay_type_nm": "마이너스통장",
        "lend_rate_type": "C",
        "lend_rate_type_nm": "변동금리",
        "lend_rate_min": Decimal("5.83"),
        "lend_rate_max": Decimal("6.23"),
        "lend_rate_avg": Decimal("5.83"),
    },
]


def test_db_columns_are_mapped_to_source_schema_keys() -> None:
    # DB의 `_raw` 접미사 컬럼이 부록 B 원천 키로 바뀌어야 정규화기가 읽을 수 있다.
    candidates = build_loan_candidates(BASE_ROWS, OPTION_ROWS)

    base = candidates[0].base_data
    assert base["loan_lmt"] == "최대 3.5억원 이내 (재직기간 1년미만 시 최대 1억원 이내)"
    assert base["erly_rpay_fee"] == "중도상환금액×0.55%×(잔여일수÷3년)"
    assert base["dly_rate"] == "대출이자율+연3%(최고 연15%)"
    assert "loan_lmt_raw" not in base
    assert base["product_id"] == 25


def test_options_are_grouped_by_product() -> None:
    candidates = build_loan_candidates(BASE_ROWS, OPTION_ROWS)

    assert len(candidates) == 2
    assert candidates[0].product_name == "KB 신용대출"
    assert len(candidates[0].option_list) == 1
    assert candidates[1].product_name == "KB 비상금대출"
    assert candidates[1].option_list[0]["rpay_type_nm"] == "마이너스통장"
    # optionList 각 행에도 상품명이 들어가는 것이 부록 B 원천 형태다.
    assert candidates[1].option_list[0]["fin_prdt_nm"] == "KB 비상금대출"
    assert "product_id" not in candidates[1].option_list[0]


def test_product_without_rate_options_is_still_a_candidate() -> None:
    # 금리를 모르는 것과 상품이 없는 것은 다르다 — 조용히 빠지면 안 된다(§22.1).
    candidates = build_loan_candidates(BASE_ROWS, [])

    assert len(candidates) == 2
    assert all(candidate.option_list == () for candidate in candidates)


def test_repository_output_feeds_the_normalizer_unchanged() -> None:
    # 리포지토리 → 정규화기가 매핑 수정 없이 그대로 이어져야 한다.
    candidates = build_loan_candidates(BASE_ROWS, OPTION_ROWS)

    credit = normalize_loan_product(candidates[0].base_data, candidates[0].option_list)
    emergency = normalize_loan_product(candidates[1].base_data, candidates[1].option_list)

    # 조건부 한도라 확정 불가, 금리는 퍼센트→비율 변환.
    assert credit.max_loan_amount is None
    assert credit.options[0].annual_rate_avg == Decimal("0.0413")

    # 실제 DB 9개 대출 상품 중 유일하게 한도가 확정되는 상품.
    assert emergency.max_loan_amount == Decimal("3000000")
    assert emergency.options[0].annual_rate_avg == Decimal("0.0583")
