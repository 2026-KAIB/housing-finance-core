from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.rule_engine.product_packs.handoff import ProductCandidate

# 대출 상품을 DB에서 읽어 Rule Pack 판정 입력(`ProductCandidate`)으로 만든다.
#
# 이 계층의 존재 이유는 **DB 컬럼명과 Rule Pack/정규화기가 기대하는 원천 스키마
# 키가 다르기 때문**이다. DB는 `loan_lmt_raw`처럼 "아직 파싱 안 된 원문"임을
# 이름에 새겨두었지만(db_schema_reference.md §4), 정규화기
# (`data_pipeline/normalizers/loan_product.py`)는 부록 B의 원천 키(`loan_lmt`)를
# 기대한다. 그 매핑을 여기서 한 번만 하고, 하위 계층은 DB를 모르게 둔다.
#
# 유효기간 필터는 DESIGN §20 "계산일에 유효한 정책만 사용" 원칙을 SQL 단계에서
# 적용한 것이다. 목록에 있다는 사실만으로 유효를 가정하지 않는다(부록 B-1).

_LOAN_PRODUCT_SQL = text("""
    SELECT p.id,
           p.fin_co_no,
           p.kor_co_nm,
           p.fin_prdt_nm,
           p.source_type,
           p.verified_at,
           p.regulatory_review_no,
           p.regulatory_review_date,
           p.effective_start,
           p.effective_end,
           p.join_way,
           p.join_deny,
           p.join_member,
           p.spcl_cnd,
           p.etc_note,
           c.code AS category_code,
           d.loan_lmt_raw,
           d.loan_inci_expn,
           d.erly_rpay_fee_raw,
           d.dly_rate_raw
      FROM financial_products p
      JOIN product_categories c ON c.id = p.category_id
      JOIN loan_product_details d ON d.product_id = p.id
     WHERE c.product_kind = 'loan'
       AND p.superseded_at IS NULL
       AND (p.effective_start IS NULL OR p.effective_start <= :as_of)
       AND (p.effective_end IS NULL OR p.effective_end >= :as_of)
     ORDER BY p.id
""")

_LOAN_RATE_OPTION_SQL = text("""
    SELECT o.product_id,
           o.mrtg_type,
           o.mrtg_type_nm,
           o.rpay_type,
           o.rpay_type_nm,
           o.lend_rate_type,
           o.lend_rate_type_nm,
           o.lend_rate_min,
           o.lend_rate_max,
           o.lend_rate_avg
      FROM loan_rate_options o
     WHERE o.product_id = ANY(:product_ids)
     ORDER BY o.product_id, o.id
""")

# DB 컬럼 → 부록 B 원천 스키마 키. 이름이 다른 것만 적는다.
_BASE_COLUMN_ALIASES = {
    "loan_lmt_raw": "loan_lmt",
    "erly_rpay_fee_raw": "erly_rpay_fee",
    "dly_rate_raw": "dly_rate",
}


def _base_row_to_raw(row: Mapping[str, Any]) -> dict[str, Any]:
    """DB 상품 행을 부록 B `baseList` 형태로 바꾼다."""
    raw: dict[str, Any] = {}
    for column, value in row.items():
        if column == "id":
            raw["product_id"] = value
            continue
        raw[_BASE_COLUMN_ALIASES.get(column, column)] = value
    return raw


def build_loan_candidates(
    base_rows: Sequence[Mapping[str, Any]],
    option_rows: Sequence[Mapping[str, Any]],
) -> tuple[ProductCandidate, ...]:
    """상품 행과 금리옵션 행을 `ProductCandidate`로 묶는다(순수 함수).

    DB 접속 없이 테스트할 수 있도록 조회(I/O)와 분리했다. 금리옵션이 하나도 없는
    상품도 후보에서 빼지 않는다 — "금리를 모른다"는 사실은 정규화기·어댑터가
    UNKNOWN으로 보고할 몫이지, 조용히 목록에서 사라질 일이 아니다(§22.1).
    """
    options_by_product: dict[Any, list[Mapping[str, Any]]] = {}
    for option_row in option_rows:
        option = dict(option_row)
        product_id = option.pop("product_id")
        options_by_product.setdefault(product_id, []).append(option)

    candidates: list[ProductCandidate] = []
    for base_row in base_rows:
        raw_base = _base_row_to_raw(base_row)
        product_id = raw_base["product_id"]
        # optionList의 각 행에도 상품명이 들어 있는 것이 부록 B의 원천 형태다.
        option_list = tuple(
            {"fin_prdt_nm": raw_base["fin_prdt_nm"], **option}
            for option in options_by_product.get(product_id, [])
        )
        candidates.append(
            ProductCandidate(
                product_name=raw_base["fin_prdt_nm"],
                base_data=raw_base,
                option_list=option_list,
            )
        )
    return tuple(candidates)


def fetch_loan_product_candidates(
    connection: Connection,
    *,
    as_of: date,
) -> tuple[ProductCandidate, ...]:
    """계산일에 유효한 대출 상품을 모두 읽어 판정 후보로 반환한다(DESIGN §20)."""
    base_rows = [
        dict(row) for row in connection.execute(_LOAN_PRODUCT_SQL, {"as_of": as_of}).mappings()
    ]
    if not base_rows:
        return ()

    product_ids = [row["id"] for row in base_rows]
    option_rows = [
        dict(row)
        for row in connection.execute(
            _LOAN_RATE_OPTION_SQL, {"product_ids": product_ids}
        ).mappings()
    ]
    return build_loan_candidates(base_rows, option_rows)
