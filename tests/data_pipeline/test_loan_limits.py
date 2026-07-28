import itertools
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.data_pipeline.curated.loan_limits import (
    PRODUCT_LOAN_LIMITS,
    LimitKind,
    ProductLoanLimit,
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


class TestPartiallyKnownConditionsStillPickTheLowest:
    """일부 조건만 아는 경우 — 뒤 규칙이 True여도 확정으로 쓰면 안 된다.

    앞선 규칙을 판단하지 못했다면 그 규칙이 실제로 참일 수 있고, 그렇다면
    더 낮은 한도가 먼저 적용된다. 회귀 대상이던 실제 결함이다.
    """

    def test_overdraft_credit_loan_without_employment_months(self) -> None:
        # 재직 1년 미만이면 1억, 1년 이상 마통이면 1.5억. 재직기간을 모르므로 1억.
        resolved = resolve_product_limit("KB 신용대출", {"is_overdraft_type": True})
        assert resolved.amount == Decimal("100000000")
        assert resolved.is_conservative
        assert "employment_months" in resolved.assumptions[0]

    def test_sgi_one_house_owner_without_region(self) -> None:
        # 규제지역이면 2억, 비규제면 3억. 지역을 모르므로 2억.
        resolved = resolve_product_limit(
            "KB스타 전세자금대출(SGI_서울보증보험)",
            {"owned_house_count": 1, "lease_deposit": Decimal("500000000")},
        )
        assert resolved.amount == Decimal("200000000")
        assert resolved.is_conservative
        assert "is_regulated_region" in resolved.assumptions[0]

    def test_bogeumjari_multi_child_without_first_home_flag(self) -> None:
        # 4억(다자녀)과 4.2억(생애최초) 중 4억. 금액뿐 아니라 가정도 남아야 한다.
        resolved = resolve_product_limit(
            "한국주택금융공사 아낌e-보금자리론",
            {"is_multi_child_or_jeonse_fraud_victim": True},
        )
        assert resolved.amount == Decimal("400000000")
        assert resolved.is_conservative
        assert "is_first_home_buyer" in resolved.assumptions[0]

    def test_a_conservative_result_always_records_an_assumption(self) -> None:
        # 값만 맞고 근거가 없으면 사용자가 어느 쪽으로 틀렸는지 알 수 없다.
        for product_name, facts in (
            ("KB 신용대출", {"is_overdraft_type": True}),
            ("한국주택금융공사 아낌e-보금자리론", {"is_multi_child_or_jeonse_fraud_victim": True}),
        ):
            resolved = resolve_product_limit(product_name, facts)
            assert resolved.assumptions, product_name


# 속성 테스트용 후보값. 각 fact가 규칙 분기를 실제로 가르는 값이어야 한다.
_FACT_CANDIDATES: dict[str, tuple[object, ...]] = {
    "employment_months": (6, 60),
    "is_first_home_buyer": (True, False),
    "is_multi_child_or_jeonse_fraud_victim": (True, False),
    "is_newlywed_or_multi_child": (True, False),
    "is_overdraft_type": (True, False),
    "is_regulated_region": (True, False),
    "owned_house_count": (0, 1, 2),
}


def _rule_facts(limit: ProductLoanLimit) -> tuple[str, ...]:
    names: list[str] = []
    for rule in limit.rules:
        names.extend(name for name in rule.required_facts if name not in names)
    return tuple(names)


class TestPartialInputNeverExceedsFullInput:
    """부분 결측 결과는 그와 모순되지 않는 모든 완전입력 결과 이하여야 한다.

    이 모듈의 안전 계약을 상품 전체에 대해 전수 확인한다. 개별 사례 테스트는
    회귀를 막지만, 새 상품이나 새 규칙이 추가될 때 잡아 주는 것은 이 쪽이다.
    """

    @pytest.mark.parametrize("limit", PRODUCT_LOAN_LIMITS, ids=lambda x: x.product_name)
    def test_conservative_result_is_a_lower_bound(self, limit: ProductLoanLimit) -> None:
        rule_facts = _rule_facts(limit)
        if not rule_facts:
            pytest.skip("조건부 규칙이 없는 상품입니다.")

        # 비율 한도는 결측 시 UNKNOWN이므로 기준값은 항상 채워 둔다.
        fixed: dict[str, object] = {}
        if limit.deposit_ratio_fact is not None:
            fixed[limit.deposit_ratio_fact] = Decimal("10000000000")

        for omitted in range(1, len(rule_facts) + 1):
            for hidden in itertools.combinations(rule_facts, omitted):
                known = [name for name in rule_facts if name not in hidden]
                for values in itertools.product(*(_FACT_CANDIDATES[n] for n in known)):
                    partial = {**fixed, **dict(zip(known, values, strict=True))}
                    conservative = limit.resolve(partial)
                    if conservative.kind is not LimitKind.AMOUNT:
                        continue
                    assert conservative.amount is not None

                    # 가려 둔 fact를 모든 값으로 채운 완전입력과 비교한다.
                    for filled in itertools.product(*(_FACT_CANDIDATES[n] for n in hidden)):
                        full = limit.resolve({**partial, **dict(zip(hidden, filled, strict=True))})
                        if full.kind is not LimitKind.AMOUNT or full.amount is None:
                            continue
                        assert conservative.amount <= full.amount, (
                            f"{limit.product_name}: {partial} → {conservative.amount:,.0f}원이 "
                            f"완전입력 {full.amount:,.0f}원보다 큽니다."
                        )
                        if conservative.amount < full.amount:
                            assert conservative.assumptions, (
                                f"{limit.product_name}: 낮춘 결과에 가정 기록이 없습니다."
                            )


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
