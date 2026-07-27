from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.rule_engine.product_packs.handoff import ProductCandidate

# 이 계층은 DB 행을 원천 스키마 모양으로 묶는 I/O만 담당한다. 금리 단위 변환,
# 상품 가입 판정, 만기금액 계산은 각각 normalizer, Rule Pack, savings engine에 둔다.

_SAVINGS_PRODUCT_SQL = text("""
    SELECT p.id,
           p.fin_co_no,
           p.kor_co_nm,
           p.fin_prdt_nm,
           p.source_type,
           p.verified_at,
           p.dcls_month,
           p.dcls_strt_day,
           p.dcls_end_day,
           p.fin_co_subm_day,
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
           d.mtrt_int,
           d.max_limit,
           d.rate_beyond_contract_max,
           d.extra_rate_info
      FROM financial_products p
      JOIN product_categories c ON c.id = p.category_id
      JOIN savings_product_details d ON d.product_id = p.id
     WHERE c.product_kind = 'savings'
       AND p.superseded_at IS NULL
       AND p.verified_at <= :as_of
       AND (p.effective_start IS NULL OR p.effective_start <= :as_of)
       AND (p.effective_end IS NULL OR p.effective_end >= :as_of)
       AND (p.dcls_strt_day IS NULL OR p.dcls_strt_day <= :as_of)
       AND (p.dcls_end_day IS NULL OR p.dcls_end_day >= :as_of)
     ORDER BY p.id
""")

_SAVINGS_RATE_OPTION_SQL = text("""
    SELECT o.product_id,
           o.save_trm,
           o.rsrv_type,
           o.rsrv_type_nm,
           o.intr_rate_type,
           o.intr_rate_type_nm,
           o.intr_rate,
           o.intr_rate2
      FROM savings_rate_options o
     WHERE o.product_id = ANY(:product_ids)
     ORDER BY o.product_id, o.id
""")


def _base_row_to_raw(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(row)
    raw["product_id"] = raw.pop("id")
    return raw


def build_savings_candidates(
    base_rows: Sequence[Mapping[str, Any]],
    option_rows: Sequence[Mapping[str, Any]],
) -> tuple[ProductCandidate, ...]:
    """DB 상품·금리 행을 Rule Pack 입력 후보로 묶는다(순수 함수).

    옵션이 없는 상품도 후보에서 제거하지 않는다. 이후 정규화·어댑터 계층이
    계산 입력 부족을 ``UNKNOWN``으로 구분해야 하기 때문이다.
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
        product_name = str(raw_base["fin_prdt_nm"])
        option_list = tuple(
            {"fin_prdt_nm": product_name, **option}
            for option in options_by_product.get(product_id, ())
        )
        candidates.append(
            ProductCandidate(
                product_name=product_name,
                base_data=raw_base,
                option_list=option_list,
            )
        )
    return tuple(candidates)


def fetch_savings_product_candidates(
    connection: Connection,
    *,
    as_of: date,
) -> tuple[ProductCandidate, ...]:
    """기준일에 유효한 예금·적금을 DB에서 읽어 Rule Pack 후보로 반환한다."""

    base_rows = [
        dict(row)
        for row in connection.execute(
            _SAVINGS_PRODUCT_SQL,
            {"as_of": as_of},
        ).mappings()
    ]
    if not base_rows:
        return ()

    product_ids = [row["id"] for row in base_rows]
    option_rows = [
        dict(row)
        for row in connection.execute(
            _SAVINGS_RATE_OPTION_SQL,
            {"product_ids": product_ids},
        ).mappings()
    ]
    return build_savings_candidates(base_rows, option_rows)
