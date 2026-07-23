from app.rule_engine.base import RuleDecision
from app.rule_engine.common import evaluate_all


class _AlwaysPass:
    code = "ALWAYS_PASS"

    def evaluate(self, context: object) -> RuleDecision:
        return RuleDecision(rule_code=self.code, passed=True)


class _AlwaysFail:
    code = "ALWAYS_FAIL"

    def evaluate(self, context: object) -> RuleDecision:
        return RuleDecision(rule_code=self.code, passed=False, reasons=("실패 사유",))


def test_evaluate_all_eligible_when_every_rule_passes() -> None:
    result = evaluate_all([_AlwaysPass(), _AlwaysPass()], context=object())

    assert result.eligible is True
    assert result.failed_decisions == ()
    assert result.reasons == ()


def test_evaluate_all_ineligible_when_any_rule_fails() -> None:
    result = evaluate_all([_AlwaysPass(), _AlwaysFail()], context=object())

    assert result.eligible is False
    assert [d.rule_code for d in result.failed_decisions] == ["ALWAYS_FAIL"]
    assert result.reasons == ("실패 사유",)


def test_evaluate_all_with_no_rules_is_vacuously_eligible() -> None:
    result = evaluate_all([], context=object())

    assert result.eligible is True
    assert result.decisions == ()
