"""조합 엔진: 공유 예산을 한 번만 쓰는가.

이 엔진의 존재 이유가 곧 첫 번째 테스트다. 다리별 최대 한도를 더하면 DSR·현금흐름·
LTV를 다리 수만큼 중복 사용하므로, 조합 총액은 **개별 최대값의 합보다 작아야** 한다.
"""

from decimal import Decimal

import pytest

from app.data_pipeline.curated.loan_combinations import (
    HF_BOGEUMJARI,
    KB_CREDIT,
    KB_MORTGAGE,
    resolve_combination,
)
from app.engines.loan.combination import build_loan_combinations
from app.engines.loan.combination_models import (
    CombinationStatus,
    CreditStressRegime,
    LoanCombinationBudget,
    LoanCombinationPolicy,
    LoanLegCandidate,
    LoanLegKind,
)
from app.engines.loan.formulas import pmt
from app.engines.recommendation.models import ScoreStatus

_CREDIT_THRESHOLD = Decimal("100000000")


def _budget(**overrides: object) -> LoanCombinationBudget:
    defaults: dict[str, object] = {
        "annual_income": Decimal("60000000"),
        "existing_annual_debt_service": Decimal(0),
        "safe_dsr": Decimal("0.40"),
        "post_purchase_monthly_income": Decimal("5000000"),
        "post_purchase_monthly_expense": Decimal("2500000"),
        "other_existing_monthly_debt_service": Decimal(0),
        "buffer_target": Decimal("300000"),
        "ltv_limit_amount": Decimal("350000000"),
        "required_amount": Decimal("400000000"),
        "credit_stress_threshold": _CREDIT_THRESHOLD,
        "existing_credit_loan_balance": Decimal(0),
    }
    defaults.update(overrides)
    return LoanCombinationBudget(**defaults)  # type: ignore[arg-type]


def _mortgage(**overrides: object) -> LoanLegCandidate:
    defaults: dict[str, object] = {
        "candidate_id": "mortgage-fixed",
        "product_id": "kb-mortgage",
        "product_name": KB_MORTGAGE,
        "option_name": "고정·원리금균등",
        "kind": LoanLegKind.MORTGAGE,
        "annual_rate": Decimal("0.04"),
        "assessment_annual_rate": Decimal("0.07"),
        "months": 360,
        "maximum_amount": Decimal("200000000"),
        "additional_financial_cost": Decimal("500000"),
        "repayment_flexibility_score": Decimal("0.8"),
    }
    defaults.update(overrides)
    return LoanLegCandidate(**defaults)  # type: ignore[arg-type]


def _credit(**overrides: object) -> LoanLegCandidate:
    defaults: dict[str, object] = {
        "candidate_id": "credit-var",
        "product_id": "kb-credit",
        "product_name": KB_CREDIT,
        "option_name": "변동·원리금균등",
        "kind": LoanLegKind.CREDIT,
        "annual_rate": Decimal("0.06"),
        "assessment_annual_rate": Decimal("0.075"),
        "months": 60,
        "maximum_amount": Decimal("350000000"),
        "additional_financial_cost": Decimal("100000"),
        "repayment_flexibility_score": Decimal("0.5"),
    }
    defaults.update(overrides)
    return LoanLegCandidate(**defaults)  # type: ignore[arg-type]


def _gate(product_names):  # noqa: ANN001, ANN202 - Protocol 구조만 맞추면 된다
    return resolve_combination(product_names)


def _run(candidates, budget=None, **kwargs):  # noqa: ANN001, ANN003
    return build_loan_combinations(
        candidates,
        budget or _budget(),
        combination_gate=_gate,
        **kwargs,
    )


def _solo_amount(candidate: LoanLegCandidate, budget: LoanCombinationBudget) -> Decimal:
    """이 다리 하나만 썼을 때의 최대 금액."""
    result = build_loan_combinations([candidate], budget, combination_gate=_gate)
    assert result.plans, result.reasons
    return max(plan.total_amount for plan in result.plans)


class TestSharedBudgetIsSpentOnce:
    """이 엔진이 존재하는 이유."""

    def test_the_combination_is_smaller_than_the_sum_of_individual_maximums(self) -> None:
        budget = _budget()
        mortgage, credit = _mortgage(), _credit()

        naive_sum = _solo_amount(mortgage, budget) + _solo_amount(credit, budget)
        result = _run([mortgage, credit], budget)
        best = result.best
        assert best is not None

        # 두 다리를 함께 쓴 조합이 실제로 나왔는지 먼저 확인한다.
        combined = next(plan for plan in result.plans if plan.leg_count == 2)

        assert combined.total_amount < naive_sum, (
            f"조합 {combined.total_amount:,.0f}원이 개별 합 {naive_sum:,.0f}원보다 "
            "작지 않다 — 공유 예산을 두 번 쓴 것이다"
        )

    def test_every_plan_respects_the_dsr_budget(self) -> None:
        """심사금리 기준 DSR이 안전기준을 넘지 않는다. 예산의 정의 그대로다."""
        budget = _budget()
        result = _run([_mortgage(), _credit()], budget)

        assert result.plans
        for plan in result.plans:
            assert plan.assessment_dsr <= budget.safe_dsr, plan.plan_id

    def test_every_plan_keeps_the_buffer(self) -> None:
        """실제 금리 기준 월 잉여가 Buffer 이상 남는다(부록 A-8)."""
        budget = _budget()
        result = _run([_mortgage(), _credit()], budget)

        assert result.plans
        for plan in result.plans:
            assert plan.post_purchase_monthly_surplus >= budget.buffer_target, plan.plan_id

    def test_two_mortgages_share_one_ltv_ceiling(self) -> None:
        """담보가 같은 주택이므로 LTV 한도는 하나다."""
        budget = _budget(ltv_limit_amount=Decimal("150000000"))
        first = _mortgage(
            candidate_id="m1", product_id="p1", maximum_amount=Decimal("300000000")
        )
        second = _mortgage(
            candidate_id="m2",
            product_id="p2",
            product_name="KB스타 아파트담보대출(주택자금)",
            maximum_amount=Decimal("300000000"),
        )

        # 검수표가 이 쌍을 미확인으로 막으므로, 게이트를 열어 예산 계산만 본다.
        result = build_loan_combinations(
            [first, second],
            budget,
            combination_gate=lambda names: _AllowAll(),
        )

        for plan in result.plans:
            mortgage_total = sum(
                (leg.amount for leg in plan.legs if leg.kind is LoanLegKind.MORTGAGE),
                Decimal(0),
            )
            assert mortgage_total <= budget.ltv_limit_amount, plan.plan_id

    def test_a_credit_leg_does_not_consume_the_ltv_budget(self) -> None:
        """담보가 달라 LTV에 걸리지 않는다 — 그래서 조합이 의미가 있다."""
        budget = _budget(ltv_limit_amount=Decimal("200000000"))
        result = _run([_mortgage(), _credit()], budget)

        combined = next(plan for plan in result.plans if plan.leg_count == 2)
        assert combined.total_amount > budget.ltv_limit_amount


class _AllowAll:
    """LTV 예산만 검증할 때 쓰는 게이트 대역."""

    is_executable = True
    blocking_pairs: tuple = ()
    unknown_pairs: tuple = ()
    sources: tuple = ()


class TestTheDuplicateUseGate:
    def test_without_a_gate_no_multi_leg_combination_is_built(self) -> None:
        """검수표 없이 조합하면 확인되지 않은 대안을 내보낸다."""
        result = build_loan_combinations([_mortgage(), _credit()], _budget())

        assert all(plan.leg_count == 1 for plan in result.plans)
        assert any(
            "loan_combination_gate" in item.missing_inputs for item in result.unresolved
        )

    def test_a_blocked_pair_never_appears_as_a_plan(self) -> None:
        """보금자리론 + 은행 주담대는 근저당권 순위 요건 위반이다."""
        bogeumjari = _mortgage(
            candidate_id="bogeumjari",
            product_id="hf-bogeumjari",
            product_name=HF_BOGEUMJARI,
        )
        result = _run([_mortgage(), bogeumjari])

        for plan in result.plans:
            assert plan.leg_count == 1, "차단된 쌍이 조합으로 나왔다"
        assert result.blocked
        assert any("1순위" in reason for item in result.blocked for reason in item.reasons)
        assert any(item.sources for item in result.blocked)

    def test_an_unknown_pair_is_reported_with_what_to_verify(self) -> None:
        second_mortgage = _mortgage(
            candidate_id="m2",
            product_id="p2",
            product_name="KB스타 아파트담보대출(주택자금)",
        )
        result = _run([_mortgage(), second_mortgage])

        assert all(plan.leg_count == 1 for plan in result.plans)
        assert any(
            name.startswith("duplicate_use:")
            for item in result.unresolved
            for name in item.missing_inputs
        )

    def test_a_verified_pair_does_produce_a_two_leg_plan(self) -> None:
        result = _run([_mortgage(), _credit()])

        assert any(plan.leg_count == 2 for plan in result.plans)


class TestCreditStressThreshold:
    """유일한 비선형 구간을 어느 쪽으로도 뭉개지 않는다."""

    def test_below_the_threshold_the_credit_leg_is_capped_at_the_headroom(self) -> None:
        """문턱 위 심사금리를 모르면 문턱까지만 배분한다."""
        budget = _budget(
            annual_income=Decimal("200000000"),  # DSR 예산을 넉넉하게
            post_purchase_monthly_income=Decimal("20000000"),
            existing_credit_loan_balance=Decimal("20000000"),
        )
        result = _run([_credit(assessment_annual_rate_above_credit_threshold=None)], budget)

        assert result.plans
        for plan in result.plans:
            assert plan.credit_regime is CreditStressRegime.BELOW
            credit_total = sum(
                (leg.amount for leg in plan.legs if leg.kind is LoanLegKind.CREDIT),
                Decimal(0),
            )
            assert credit_total <= _CREDIT_THRESHOLD - Decimal("20000000")

    def test_the_above_regime_is_reported_missing_when_its_rate_is_unknown(self) -> None:
        budget = _budget(
            annual_income=Decimal("200000000"),
            post_purchase_monthly_income=Decimal("20000000"),
        )
        result = _run([_credit(assessment_annual_rate_above_credit_threshold=None)], budget)

        assert any(
            any("assessment_rate_above_credit_threshold" in name for name in item.missing_inputs)
            for item in result.unresolved
        )

    def test_a_known_above_threshold_rate_opens_the_larger_plan(self) -> None:
        """가산금리를 알면 문턱 위 구간도 계산하고, 더 큰 금액이 가능해진다."""
        budget = _budget(
            annual_income=Decimal("200000000"),
            post_purchase_monthly_income=Decimal("20000000"),
        )
        result = _run(
            [_credit(assessment_annual_rate_above_credit_threshold=Decimal("0.09"))],
            budget,
        )

        above = [
            plan for plan in result.plans if plan.credit_regime is CreditStressRegime.ABOVE
        ]
        assert above, "문턱 위 구간이 계산되지 않았다"
        for plan in above:
            credit_total = sum(
                (leg.amount for leg in plan.legs if leg.kind is LoanLegKind.CREDIT),
                Decimal(0),
            )
            assert credit_total > _CREDIT_THRESHOLD, "문턱 위 구간의 전제가 성립해야 한다"
            # 가산금리가 실제로 심사에 반영됐는지.
            leg = next(item for item in plan.legs if item.kind is LoanLegKind.CREDIT)
            assert leg.assessment_annual_rate == Decimal("0.09")

    def test_an_unknown_existing_balance_blocks_credit_combinations(self) -> None:
        """잔액을 모르면 계산하지 않는다 — 0으로 뭉개면 가산금리가 빠진다."""
        budget = _budget(existing_credit_loan_balance=None)
        result = _run([_mortgage(), _credit()], budget)

        assert all(
            all(leg.kind is not LoanLegKind.CREDIT for leg in plan.legs)
            for plan in result.plans
        )
        assert any(
            "existing_credit_loan_balance" in item.missing_inputs
            for item in result.unresolved
        )

    def test_a_mortgage_only_plan_survives_an_already_exceeded_balance(self) -> None:
        """기존 신용대출 잔액이 이미 문턱을 넘어도 주담대 단독 조합은 살아 있다.

        문턱 전제 검사를 신용대출 없는 조합에까지 적용하면 이 조합이 사라진다.
        """
        budget = _budget(existing_credit_loan_balance=Decimal("150000000"))
        result = _run([_mortgage()], budget)

        assert result.plans
        assert all(
            plan.credit_regime is CreditStressRegime.NOT_APPLICABLE for plan in result.plans
        )


class TestRankingAndTopN:
    def test_at_most_top_n_plans_are_returned(self) -> None:
        result = _run(
            [_mortgage(), _credit()],
            policy=LoanCombinationPolicy(top_n=2),
        )

        assert len(result.plans) <= 2

    def test_fewer_than_top_n_is_reported_as_is(self) -> None:
        """자리를 채우려고 탈락한 조합을 끼워 넣지 않는다."""
        result = _run([_mortgage()], policy=LoanCombinationPolicy(top_n=5))

        assert 0 < len(result.plans) < 5

    def test_funding_coverage_outranks_the_section_14_score(self) -> None:
        """조달액이 다른 조합에 §14를 그대로 쓰면 덜 빌리는 쪽이 항상 이긴다.

        §14.1 상환가능성(가중치 0.30)은 낮은 DSR을 우대한다. 실측에서 주담대 단독
        2.0억(부족 2.0억)이 58.2점, 조합 2.33억(부족 1.67억)이 44.7점이었다. 집을
        사려는 사용자에게는 뒤집힌 순서라, 충족률을 먼저 본다.
        """
        result = _run([_mortgage(), _credit()])

        amounts = [plan.total_amount for plan in result.plans]
        assert amounts == sorted(amounts, reverse=True), (
            "조달액이 큰 조합이 앞에 와야 한다"
        )
        assert result.plans[0].leg_count == 2, "가장 많이 조달하는 조합이 1위여야 한다"

    def test_within_the_same_coverage_the_score_decides(self) -> None:
        """같은 조달 수준 안에서는 §14가 우열을 가린다 — 그게 §14의 설계된 용법이다."""
        result = _run([_mortgage(), _credit()])

        by_amount: dict[Decimal, list[Decimal | None]] = {}
        for plan in result.plans:
            by_amount.setdefault(plan.total_amount, []).append(plan.score)
        for scores in by_amount.values():
            known = [value for value in scores if value is not None]
            assert known == sorted(known, reverse=True)

    def test_an_unscored_plan_never_outranks_a_scored_one(self) -> None:
        """점수 미확인을 "나쁘지 않음"으로 읽으면 근거 없는 1위가 나온다."""
        result = _run(
            [
                _mortgage(repayment_flexibility_score=None, additional_financial_cost=None),
                _credit(),
            ]
        )

        seen_unscored = False
        for plan in result.plans:
            if plan.score is None:
                seen_unscored = True
            else:
                assert not seen_unscored, "점수 없는 조합이 점수 있는 조합보다 앞에 있다"

    def test_the_result_is_deterministic(self) -> None:
        first = _run([_mortgage(), _credit()])
        second = _run([_mortgage(), _credit()])

        assert [plan.plan_id for plan in first.plans] == [
            plan.plan_id for plan in second.plans
        ]
        assert [plan.total_amount for plan in first.plans] == [
            plan.total_amount for plan in second.plans
        ]


class TestScoring:
    def test_the_score_uses_the_shared_section_14_weights(self) -> None:
        """조합 전용 가중치를 만들지 않는다 — §14 하나에서만 나온다."""
        result = _run([_mortgage(), _credit()])
        plan = result.best
        assert plan is not None
        assert plan.score is not None
        assert Decimal(0) <= plan.score <= Decimal(100)
        assert plan.score_status is not ScoreStatus.UNAVAILABLE

    def test_a_missing_component_is_renormalised_not_zeroed(self) -> None:
        """부록 A-10 — 결측 항목은 0점이 아니라 가중치 재정규화 대상이다."""
        result = _run([_mortgage(repayment_flexibility_score=None), _credit()])
        plan = next(
            item
            for item in result.plans
            if any(leg.candidate_id == "mortgage-fixed" for leg in item.legs)
            and item.leg_count == 1
        )

        assert "repayment_flexibility" in plan.missing_score_components
        assert plan.score_completeness < Decimal(1)
        if plan.score is not None:
            assert plan.score > Decimal(0), "결측을 0점으로 처리하면 안 된다"

    def test_cost_is_not_scored_when_a_cost_is_unknown(self) -> None:
        result = _run([_mortgage(additional_financial_cost=None), _credit()])

        for plan in result.plans:
            assert plan.total_financial_cost is None or plan.score_components is not None

    def test_components_are_all_within_zero_and_one(self) -> None:
        result = _run([_mortgage(), _credit()])

        for plan in result.plans:
            assert plan.score_components is not None
            for value in (
                plan.score_components.repayment_capacity,
                plan.score_components.total_cost,
                plan.score_components.crisis_resilience,
                plan.score_components.interest_stability,
                plan.score_components.repayment_flexibility,
            ):
                if value is not None:
                    assert Decimal(0) <= value <= Decimal(1)


class TestMonetaryConsistency:
    def test_monthly_payments_come_from_pmt_not_from_the_factor(self) -> None:
        """계수는 예산 환산 도구이고, 보이는 금액은 저장소 전역과 같은 함수에서 나온다."""
        result = _run([_mortgage(), _credit()])

        for plan in result.plans:
            for leg in plan.legs:
                assert leg.monthly_payment == pmt(leg.amount, leg.annual_rate, leg.months)
                assert leg.assessment_monthly_payment == pmt(
                    leg.amount, leg.assessment_annual_rate, leg.months
                )

    def test_plan_totals_equal_the_sum_of_their_legs(self) -> None:
        result = _run([_mortgage(), _credit()])

        for plan in result.plans:
            assert plan.total_amount == sum((leg.amount for leg in plan.legs), Decimal(0))
            assert plan.monthly_payment == sum(
                (leg.monthly_payment for leg in plan.legs), Decimal(0)
            )

    def test_the_shortfall_is_measured_against_the_required_amount(self) -> None:
        budget = _budget()
        result = _run([_mortgage(), _credit()], budget)

        for plan in result.plans:
            expected = max(budget.required_amount - plan.total_amount, Decimal(0))
            assert plan.funding_shortfall == expected

    def test_amounts_are_whole_won(self) -> None:
        """배분액을 원 단위로 내려 예산 초과와 소수점 금액을 함께 없앤다.

        계수로 환산한 금액을 그대로 쓰면 `pmt()` 재계산에서 예산을 미세하게 넘는다
        (실측 DSR 0.4000000000000000000000000002). 내림은 항상 과소평가 방향이다.
        """
        result = _run([_mortgage(), _credit()])

        for plan in result.plans:
            for leg in plan.legs:
                assert leg.amount == leg.amount.to_integral_value(), leg.candidate_id

    def test_binding_constraints_are_named(self) -> None:
        """"왜 더 못 빌리는가"에 답할 수 있어야 한다(§19)."""
        result = _run([_mortgage(), _credit()])

        for plan in result.plans:
            assert plan.binding_constraints


class TestProductAndMinimumRules:
    def test_two_options_of_the_same_product_are_never_combined(self) -> None:
        fixed = _mortgage(candidate_id="m-fixed")
        variable = _mortgage(
            candidate_id="m-var",
            annual_rate=Decimal("0.035"),
            assessment_annual_rate=Decimal("0.065"),
        )

        result = build_loan_combinations(
            [fixed, variable],
            _budget(),
            combination_gate=lambda names: _AllowAll(),
        )

        for plan in result.plans:
            assert len({leg.product_id for leg in plan.legs}) == plan.leg_count

    def test_a_leg_below_its_product_minimum_is_dropped(self) -> None:
        """금액을 최소금액까지 끌어올리지 않는다 — 그러면 예산 제약을 위반한다."""
        budget = _budget(annual_income=Decimal("30000000"))
        big_minimum = _credit(minimum_amount=Decimal("300000000"))

        result = _run([_mortgage(), big_minimum], budget)

        for plan in result.plans:
            assert all(leg.candidate_id != "credit-var" for leg in plan.legs)

    def test_an_uncapped_product_is_not_treated_as_unknown(self) -> None:
        """maximum_amount=None은 확인된 무제한이며 계산을 막지 않는다."""
        result = _run([_mortgage(maximum_amount=None)])

        assert result.plans
        assert result.status in (CombinationStatus.COMPLETE, CombinationStatus.PARTIAL)


class TestDegenerateInputs:
    def test_no_candidates_is_missing_not_infeasible(self) -> None:
        """후보 0건과 "가능한 조합이 없음"은 다른 상태다."""
        result = build_loan_combinations([], _budget(), combination_gate=_gate)

        assert result.status is CombinationStatus.UNRESOLVED
        assert result.missing_inputs == ("loan_leg_candidates",)

    def test_duplicate_candidate_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="candidate_id"):
            build_loan_combinations([_mortgage(), _mortgage()], _budget())

    def test_a_borrower_with_no_dsr_room_gets_no_plan(self) -> None:
        budget = _budget(
            annual_income=Decimal("20000000"),
            existing_annual_debt_service=Decimal("8000000"),
        )
        result = _run([_mortgage(), _credit()], budget)

        assert result.status is CombinationStatus.INFEASIBLE
        assert result.plans == ()
        assert result.infeasible

    def test_partial_is_distinguished_from_complete(self) -> None:
        """전액 조달하지 못하는 조합만 있으면 PARTIAL이다."""
        budget = _budget(required_amount=Decimal("900000000"))
        result = _run([_mortgage(), _credit()], budget)

        assert result.status is CombinationStatus.PARTIAL
        assert all(not plan.covers_required_amount for plan in result.plans)
        assert any("전액 조달하지 못" in reason for reason in result.reasons)
