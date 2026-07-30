"""중복 이용 검수표: 확인하지 못한 조합을 실행 가능으로 읽지 않는가.

이 표의 존재 이유는 원천 데이터에 중복 이용 조항이 **없다**는 사실이다. 그래서
가장 중요한 불변식은 "미확인은 통과가 아니다"이고, 아래 테스트가 그것을 고정한다.
"""

import pytest

from app.data_pipeline.curated.loan_combinations import (
    COMBINATION_RULES,
    CREDIT_PRODUCTS,
    HF_BOGEUMJARI,
    KB_CREDIT,
    KB_EMERGENCY_CREDIT,
    KB_MORTGAGE,
    KB_PAYROLL_CREDIT,
    KB_STAR_APARTMENT,
    MORTGAGE_PRODUCTS,
    CombinationRule,
    CombinationVerdict,
    coverage_report,
    describe_missing_verification,
    get_combination_rule,
    known_product_names,
    resolve_combination,
    unverified_pairs,
)
from app.data_pipeline.curated.loan_limits import PRODUCT_LOAN_LIMITS


class TestVerifiedBlocks:
    """1차 출처로 확인해 불가로 판정한 조합."""

    @pytest.mark.parametrize("bank_mortgage", [KB_MORTGAGE, KB_STAR_APARTMENT])
    def test_bogeumjari_cannot_stack_with_a_bank_mortgage(self, bank_mortgage: str) -> None:
        """보금자리론은 1순위 근저당 요건이 있고 은행 주담대는 허용 예외가 아니다.

        HF 업무처리기준 제9장 2의 선순위 허용 목록은 주택도시기금대출·공사
        보금자리론·나라사랑대출뿐이다.
        """
        result = resolve_combination([HF_BOGEUMJARI, bank_mortgage])

        assert result.verdict is CombinationVerdict.BLOCKED
        assert not result.is_executable
        assert len(result.blocking_pairs) == 1
        (pair, note) = result.blocking_pairs[0]
        assert set(pair) == {HF_BOGEUMJARI, bank_mortgage}
        assert "1순위" in note
        assert any("제9장" in source for source in result.sources)

    def test_a_blocked_pair_reports_a_reason_not_just_a_verdict(self) -> None:
        """"안 됨"만 내면 사용자가 다음 행동을 못 정한다(§19)."""
        result = resolve_combination([HF_BOGEUMJARI, KB_MORTGAGE])

        (_pair, note) = result.blocking_pairs[0]
        assert len(note) > 40
        assert result.sources


class TestVerifiedAllows:
    """담보가 달라 병행이 확인된 조합."""

    @pytest.mark.parametrize("mortgage", MORTGAGE_PRODUCTS)
    @pytest.mark.parametrize("credit", CREDIT_PRODUCTS)
    def test_a_mortgage_and_a_credit_loan_can_run_together(
        self,
        mortgage: str,
        credit: str,
    ) -> None:
        result = resolve_combination([mortgage, credit])

        assert result.verdict is CombinationVerdict.ALLOWED
        assert result.is_executable
        assert result.blocking_pairs == ()
        assert result.unknown_pairs == ()

    def test_the_allow_note_says_the_budget_must_be_shared(self) -> None:
        """이 표가 조합을 열어 주는 순간이 DSR 예산 이중사용이 생기는 지점이다.

        허용 근거에 그 경고를 함께 실어, 표를 읽는 사람이 개별 한도를 더하는
        구현으로 가지 않게 한다.
        """
        rule = get_combination_rule(KB_MORTGAGE, KB_CREDIT)

        assert rule is not None
        assert rule.verdict is CombinationVerdict.ALLOWED
        assert "DSR" in rule.note
        assert "두 번" in rule.note


class TestUnknownIsNotAPass:
    """미확인은 통과가 아니다 — 이 표의 핵심 규약."""

    def test_an_unverified_pair_is_hidden_from_the_default_lookup(self) -> None:
        assert get_combination_rule(KB_MORTGAGE, KB_STAR_APARTMENT) is None

    def test_it_becomes_visible_only_when_explicitly_requested(self) -> None:
        rule = get_combination_rule(
            KB_MORTGAGE,
            KB_STAR_APARTMENT,
            allow_unverified=True,
        )

        assert rule is not None
        assert rule.verdict is CombinationVerdict.UNKNOWN
        assert rule.verified is False

    def test_two_same_bank_mortgages_are_unknown_not_allowed(self) -> None:
        result = resolve_combination([KB_MORTGAGE, KB_STAR_APARTMENT])

        assert result.verdict is CombinationVerdict.UNKNOWN
        assert not result.is_executable
        assert result.unknown_pairs

    @pytest.mark.parametrize(
        "pair",
        [
            (KB_CREDIT, KB_PAYROLL_CREDIT),
            (KB_CREDIT, KB_EMERGENCY_CREDIT),
            (KB_PAYROLL_CREDIT, KB_EMERGENCY_CREDIT),
        ],
    )
    def test_stacking_two_credit_loans_is_unknown(self, pair: tuple[str, str]) -> None:
        result = resolve_combination(list(pair))

        assert result.verdict is CombinationVerdict.UNKNOWN

    def test_a_product_absent_from_the_table_is_unknown(self) -> None:
        result = resolve_combination([KB_MORTGAGE, "표에 없는 상품"])

        assert result.verdict is CombinationVerdict.UNKNOWN
        assert result.unknown_pairs


class TestSubsetClosure:
    def test_a_single_product_is_not_a_combination(self) -> None:
        assert resolve_combination([KB_MORTGAGE]).verdict is CombinationVerdict.ALLOWED

    def test_duplicates_collapse_to_a_single_product(self) -> None:
        assert (
            resolve_combination([KB_MORTGAGE, KB_MORTGAGE]).verdict
            is CombinationVerdict.ALLOWED
        )

    def test_one_unknown_pair_does_not_get_covered_by_verified_pairs(self) -> None:
        """확인된 쌍이 둘이어도 모르는 쌍 하나가 조합 전체를 미확정으로 만든다.

        주담대 2건 + 신용 1건: 주담대×신용 두 쌍은 ALLOWED지만 주담대×주담대가
        UNKNOWN이다. 다수결로 통과시키면 확인하지 않은 조합을 추천한다.
        """
        result = resolve_combination([KB_MORTGAGE, KB_STAR_APARTMENT, KB_CREDIT])

        assert result.verdict is CombinationVerdict.UNKNOWN
        assert len(result.unknown_pairs) == 1

    def test_a_blocked_pair_outranks_unknown_pairs(self) -> None:
        """BLOCKED가 UNKNOWN보다 우선한다 — 확인된 사유를 보여줄 수 있으니까."""
        result = resolve_combination([HF_BOGEUMJARI, KB_MORTGAGE, KB_STAR_APARTMENT])

        assert result.verdict is CombinationVerdict.BLOCKED
        assert result.blocking_pairs

    def test_order_does_not_change_the_verdict(self) -> None:
        forward = resolve_combination([HF_BOGEUMJARI, KB_CREDIT, KB_MORTGAGE])
        backward = resolve_combination([KB_MORTGAGE, KB_CREDIT, HF_BOGEUMJARI])

        assert forward.verdict is backward.verdict
        assert forward.blocking_pairs[0][0] == backward.blocking_pairs[0][0]


class TestTableIntegrity:
    def test_product_names_match_the_limit_table(self) -> None:
        """두 표가 다른 이름을 쓰면 한쪽이 조용히 결측으로 빠진다."""
        limit_names = {limit.product_name for limit in PRODUCT_LOAN_LIMITS}

        for name in known_product_names():
            assert name in limit_names, f"한도표에 없는 상품명: {name}"

    def test_every_rule_carries_a_source_and_a_reason(self) -> None:
        for rule in COMBINATION_RULES:
            assert rule.source.strip()
            assert rule.note.strip()

    def test_verified_rules_are_never_unknown(self) -> None:
        """확인했다면 결론이 나와야 한다. verified=True + UNKNOWN은 모순이다."""
        for rule in COMBINATION_RULES:
            if rule.verified:
                assert rule.verdict is not CombinationVerdict.UNKNOWN

    def test_unverified_rules_are_always_unknown(self) -> None:
        """미확인 줄이 ALLOWED/BLOCKED를 주장하면 게이트가 무의미해진다."""
        for rule in COMBINATION_RULES:
            if not rule.verified:
                assert rule.verdict is CombinationVerdict.UNKNOWN

    def test_a_self_pair_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="같은 상품"):
            CombinationRule(
                products=(KB_MORTGAGE, KB_MORTGAGE),
                verdict=CombinationVerdict.ALLOWED,
                source="출처",
                note="근거",
            )

    def test_a_rule_without_a_source_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="출처"):
            CombinationRule(
                products=(KB_MORTGAGE, KB_CREDIT),
                verdict=CombinationVerdict.ALLOWED,
                source="   ",
                note="근거",
            )


class TestVerificationBacklog:
    def test_the_pending_list_is_not_empty_and_is_explicit(self) -> None:
        """검수 대기 목록을 코드가 스스로 보고한다 — 잊히지 않게."""
        pending = unverified_pairs()

        assert pending
        assert (
            len(pending)
            == len([rule for rule in COMBINATION_RULES if not rule.verified])
        )

    def test_each_pending_pair_says_what_to_check(self) -> None:
        for line in describe_missing_verification():
            assert " + " in line
            assert len(line) > 60

    def test_coverage_report_separates_covered_from_missing(self) -> None:
        # 라벨은 정렬된 쌍 키로 만들어지므로 선언 순서를 가정하지 않는다.
        report = coverage_report([KB_MORTGAGE, KB_STAR_APARTMENT, KB_CREDIT])

        def has_pair(labels: tuple[str, ...], first: str, second: str) -> bool:
            return any(first in label and second in label for label in labels)

        # 주담대 × 신용 두 쌍은 확인됨.
        assert has_pair(report["covered"], KB_MORTGAGE, KB_CREDIT)
        assert has_pair(report["covered"], KB_STAR_APARTMENT, KB_CREDIT)
        # 주담대 × 주담대는 미확인.
        assert has_pair(report["missing"], KB_MORTGAGE, KB_STAR_APARTMENT)
        assert len(report["covered"]) == 2
        assert len(report["missing"]) == 1
