import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.data_pipeline.curated.loan_limits import (
    PRODUCT_LOAN_LIMITS,
    LimitKind,
    get_product_loan_limit,
    resolve_product_limit,
)

# 이 테스트의 핵심 주장은 두 가지다.
#   1. 조건을 알면 원문 그대로의 한도가 나온다.
#   2. 조건을 모르면 **더 낮은** 한도가 나온다 (과대평가 금지).
# 원문 대조는 selected_23_products.json이 있을 때만 수행한다 — 이 파일은
# 저장소에 커밋하지 않기로 한 원천 데이터라 CI에는 없을 수 있다.

_SOURCE_JSON = Path(__file__).resolve().parents[2] / "selected_23_products.json"
_LOAN_CATEGORIES = ("주택담보대출", "전세자금대출", "개인신용대출")


def _amount(product_name: str, facts: dict[str, object]) -> Decimal:
    resolved = resolve_product_limit(product_name, facts)
    assert resolved.kind is LimitKind.AMOUNT, resolved
    assert resolved.amount is not None
    return resolved.amount


class TestConditionsKnown:
    def test_bogeumjari_first_home_buyer_gets_the_highest_tier(self) -> None:
        assert _amount(
            "한국주택금융공사 아낌e-보금자리론",
            {"is_first_home_buyer": True, "is_multi_child_or_jeonse_fraud_victim": False},
        ) == Decimal("420000000")

    def test_bogeumjari_multi_child_gets_the_middle_tier(self) -> None:
        assert _amount(
            "한국주택금융공사 아낌e-보금자리론",
            {"is_first_home_buyer": False, "is_multi_child_or_jeonse_fraud_victim": True},
        ) == Decimal("400000000")

    def test_bogeumjari_plain_applicant_gets_the_base_tier(self) -> None:
        assert _amount(
            "한국주택금융공사 아낌e-보금자리론",
            {"is_first_home_buyer": False, "is_multi_child_or_jeonse_fraud_victim": False},
        ) == Decimal("360000000")

    def test_credit_loan_short_tenure_beats_the_overdraft_tier(self) -> None:
        # 원문상 재직 1년 미만(1억)과 종합통장자동대출(1.5억)이 동시에 성립할 수
        # 있다. 둘 다 걸리면 낮은 쪽이 남아야 한다.
        assert _amount(
            "KB 신용대출",
            {"employment_months": 6, "is_overdraft_type": True},
        ) == Decimal("100000000")

    def test_credit_loan_overdraft_with_long_tenure(self) -> None:
        assert _amount(
            "KB 신용대출",
            {"employment_months": 60, "is_overdraft_type": True},
        ) == Decimal("150000000")

    def test_credit_loan_default_tier(self) -> None:
        assert _amount(
            "KB 신용대출",
            {"employment_months": 60, "is_overdraft_type": False},
        ) == Decimal("350000000")

    def test_sgi_jeonse_regulated_region_one_house_owner(self) -> None:
        # 규제지역 1주택자 2억원. 임차보증금 80%(4억)보다 낮으므로 2억이 남는다.
        assert _amount(
            "KB스타 전세자금대출(SGI_서울보증보험)",
            {
                "owned_house_count": 1,
                "is_regulated_region": True,
                "lease_deposit": Decimal("500000000"),
            },
        ) == Decimal("200000000")

    def test_sgi_jeonse_deposit_ratio_can_bind_instead_of_the_flat_cap(self) -> None:
        # 무주택 정액 한도는 5억이지만 임차보증금 2억의 80% = 1.6억이 더 낮다.
        assert _amount(
            "KB스타 전세자금대출(SGI_서울보증보험)",
            {
                "owned_house_count": 0,
                "is_regulated_region": False,
                "lease_deposit": Decimal("200000000"),
            },
        ) == Decimal("160000000")

    def test_hf_jeonse_newlywed_cap_is_lower_than_the_base(self) -> None:
        # 우대 대상이 오히려 낮은 원문 구조를 그대로 반영한다.
        assert _amount(
            "KB스타 전세자금대출(HF_한국주택금융공사)",
            {"is_newlywed_or_multi_child": True},
        ) == Decimal("200000000")
        assert _amount(
            "KB스타 전세자금대출(HF_한국주택금융공사)",
            {"is_newlywed_or_multi_child": False},
        ) == Decimal("222000000")

    def test_unconditional_products_need_no_facts(self) -> None:
        assert _amount("KB 비상금대출", {}) == Decimal("3000000")
        assert _amount("KB스타 아파트담보대출(주택자금)", {}) == Decimal("1000000000")


class TestUncappedIsNotUnknown:
    def test_mortgage_without_overdraft_has_no_product_cap(self) -> None:
        # "담보조사가격 및 소득금액 ... 에 따른 대출가능금액 이내"는 상한이
        # 없다는 뜻이지 모른다는 뜻이 아니다.
        resolved = resolve_product_limit("KB 주택담보대출", {"is_overdraft_type": False})
        assert resolved.kind is LimitKind.UNCAPPED
        assert resolved.amount is None
        assert resolved.assumptions == ()

    def test_mortgage_overdraft_form_has_a_cap(self) -> None:
        assert _amount("KB 주택담보대출", {"is_overdraft_type": True}) == Decimal("300000000")


class TestMissingConditionsFallBackToTheLowestTier:
    def test_credit_loan_without_facts_uses_the_lowest_possible_cap(self) -> None:
        resolved = resolve_product_limit("KB 신용대출", {})
        assert resolved.amount == Decimal("100000000")
        assert resolved.is_conservative
        assert "employment_months" in resolved.assumptions[0]
        assert "is_overdraft_type" in resolved.assumptions[0]

    def test_bogeumjari_without_facts_uses_the_base_not_the_uplift(self) -> None:
        resolved = resolve_product_limit("한국주택금융공사 아낌e-보금자리론", {})
        assert resolved.amount == Decimal("360000000")
        assert resolved.is_conservative

    def test_mortgage_without_facts_assumes_the_overdraft_cap(self) -> None:
        # 상한 없음(UNCAPPED)과 3억 중 무엇인지 모르면 3억을 쓴다.
        resolved = resolve_product_limit("KB 주택담보대출", {})
        assert resolved.amount == Decimal("300000000")
        assert resolved.is_conservative

    def test_salary_credit_loan_without_facts(self) -> None:
        resolved = resolve_product_limit("KB 급여이체신용대출", {})
        assert resolved.amount == Decimal("100000000")
        assert resolved.is_conservative

    def test_hug_jeonse_without_house_count_assumes_one_house_owner(self) -> None:
        resolved = resolve_product_limit(
            "KB스타 전세자금대출(HUG_주택도시보증공사)",
            {"lease_deposit": Decimal("1000000000")},
        )
        assert resolved.amount == Decimal("200000000")
        assert resolved.is_conservative


class TestRatioCapsRefuseToGuess:
    def test_missing_lease_deposit_is_unknown_not_conservative(self) -> None:
        # 비율 한도를 빠뜨리면 과소가 아니라 **과대**평가가 되므로 UNKNOWN이다.
        resolved = resolve_product_limit(
            "KB스타 전세자금대출(SGI_서울보증보험)",
            {"owned_house_count": 0, "is_regulated_region": False},
        )
        assert resolved.kind is LimitKind.UNKNOWN
        assert resolved.missing_facts == ("lease_deposit",)

    def test_unreviewed_product_is_unknown(self) -> None:
        resolved = resolve_product_limit("존재하지 않는 상품", {})
        assert resolved.kind is LimitKind.UNKNOWN
        assert resolved.amount is None


class TestTableIntegrity:
    def test_every_loan_product_in_the_source_data_is_covered(self) -> None:
        if not _SOURCE_JSON.exists():
            pytest.skip("selected_23_products.json이 없어 원문 대조를 건너뜁니다.")
        data = json.loads(_SOURCE_JSON.read_text(encoding="utf-8"))
        source_names = {
            product["baseList"]["fin_prdt_nm"]
            for category in _LOAN_CATEGORIES
            for product in data["categories"][category]
        }
        covered = {limit.product_name for limit in PRODUCT_LOAN_LIMITS}
        assert source_names == covered

    def test_source_text_matches_the_original_loan_lmt(self) -> None:
        if not _SOURCE_JSON.exists():
            pytest.skip("selected_23_products.json이 없어 원문 대조를 건너뜁니다.")
        data = json.loads(_SOURCE_JSON.read_text(encoding="utf-8"))
        for category in _LOAN_CATEGORIES:
            for product in data["categories"][category]:
                base = product["baseList"]
                limit = get_product_loan_limit(base["fin_prdt_nm"])
                assert limit is not None, base["fin_prdt_nm"]
                assert limit.source_text == base["loan_lmt"], base["fin_prdt_nm"]

    def test_no_rule_exceeds_its_products_default_cap(self) -> None:
        # 조건부 한도가 기본 한도보다 높은 것은 보금자리론의 우대 구간뿐이며,
        # 그 경우에도 "결측 시 최저값" 규칙이 기본 한도를 고르는지 확인한다.
        for limit in PRODUCT_LOAN_LIMITS:
            if limit.default_amount is None:
                continue
            resolved = limit.resolve({})
            assert resolved.amount is None or resolved.amount <= limit.default_amount
