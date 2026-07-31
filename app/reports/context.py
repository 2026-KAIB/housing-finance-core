"""전체 계산 JSON에서 개인정보를 제외한 보고서 AI 입력을 만든다.

보고서 AI는 원천 마이데이터가 아니라 이 허용목록 결과만 소비한다. 추천 결과가
있으면 대출·예적금은 검증과 순위화가 끝난 추천 요약을 우선하고, 없을 때만
하위 계산 결과를 제공한다.
"""

from collections.abc import Mapping
from typing import Any

from app.schemas.report import (
    ReportAIInput,
    ReportSection,
    ReportSections,
)
from app.schemas.simulation import CalculationSection, SectionRunStatus, SimulationResult

# 키 이름을 소문자·밑줄 기준으로 검사한다. 상품명과 시나리오명에 필요한 일반
# "name"은 막지 않고 금융 식별자·인증정보·원천 거래 묶음만 제거한다.
_BLOCKED_KEYS = {
    "account_num",
    "account_number",
    "account_no",
    "account_id",
    "account_seq",
    "bank_account_number",
    "resident_registration_number",
    "rrn",
    "birth_date",
    "phone_number",
    "email",
    "address",
    "customer_id",
    "user_id",
    "password",
    "credential",
    "access_token",
    "refresh_token",
    "raw_transactions",
    "transactions",
    "transaction_list",
    "transaction_detail",
}


def sanitize_report_facts(value: object) -> Any:
    """금융 식별자·인증정보·원천 거래 묶음을 제거한다.

    매물 보고서 계약도 같은 허용목록을 쓴다. 두 벌로 두면 한쪽만 갱신된다.
    """
    return _sanitize(value)


def _sanitize(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _BLOCKED_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def _nested_strings(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key, ())
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()


def _report_section(
    source: CalculationSection,
    *,
    facts: Mapping[str, object] | None = None,
    engine_status: str | None = None,
    missing_inputs: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    policy_sources: tuple[str, ...] = (),
) -> ReportSection:
    selected = facts if facts is not None else source.result
    sanitized = None if selected is None else _sanitize(selected)
    return ReportSection(
        run_status=source.run_status,
        engine_status=engine_status if engine_status is not None else source.engine_status,
        facts=sanitized,
        missing_inputs=tuple(dict.fromkeys(source.missing_inputs + missing_inputs)),
        reasons=tuple(dict.fromkeys(source.reasons + reasons)),
        policy_sources=tuple(dict.fromkeys(source.policy_sources + policy_sources)),
    )


def _recommendation_parts(
    result: SimulationResult,
) -> tuple[ReportSection, ReportSection, ReportSection]:
    recommendation = result.recommendation
    payload = recommendation.result
    if recommendation.run_status is SectionRunStatus.COMPLETED and payload is not None:
        savings = payload.get("savings")
        loan = payload.get("loan")
        savings_payload = savings if isinstance(savings, Mapping) else None
        loan_payload = loan if isinstance(loan, Mapping) else None

        savings_section = _report_section(
            recommendation,
            facts=savings_payload,
            engine_status=(
                str(savings_payload.get("status"))
                if savings_payload is not None
                else None
            ),
            missing_inputs=(
                _nested_strings(savings_payload, "missing_inputs")
                if savings_payload is not None
                else ()
            ),
            reasons=(
                _nested_strings(savings_payload, "reasons")
                if savings_payload is not None
                else ()
            ),
        )
        loan_section = _report_section(
            recommendation,
            facts=loan_payload,
            engine_status=(
                str(loan_payload.get("status"))
                if loan_payload is not None
                else None
            ),
            missing_inputs=(
                _nested_strings(loan_payload, "missing_inputs")
                if loan_payload is not None
                else ()
            ),
            reasons=(
                _nested_strings(loan_payload, "reasons")
                if loan_payload is not None
                else ()
            ),
            policy_sources=(
                _nested_strings(loan_payload, "policy_sources")
                if loan_payload is not None
                else ()
            ),
        )
        recommendation_facts = {
            key: value
            for key, value in payload.items()
            if key not in {"savings", "loan"}
        }
        recommendation_section = _report_section(
            recommendation,
            facts=recommendation_facts,
        )
        return savings_section, loan_section, recommendation_section

    return (
        _report_section(
            result.savings_portfolio,
            reasons=(
                "종합추천이 실행되지 않아 예적금 계산 결과는 최종 상품추천이 아닙니다.",
            ),
        ),
        _report_section(
            result.loan_simulation,
            reasons=(
                "종합추천이 실행되지 않아 대출 계산 결과는 최종 상품추천이 아닙니다.",
            ),
        ),
        _report_section(recommendation),
    )


def build_report_ai_input(result: SimulationResult) -> ReportAIInput:
    """전체 결과에서 보고서 설명에 필요한 허용목록 JSON만 만든다."""

    savings, loan, recommendation = _recommendation_parts(result)
    sections = ReportSections(
        financial_diagnosis=_report_section(result.cashflow),
        savings=savings,
        loan=loan,
        recommendation=recommendation,
        stress_test=_report_section(result.stress_test),
        strategy_comparison=_report_section(result.strategy_comparison),
    )
    section_values = (
        sections.financial_diagnosis,
        sections.savings,
        sections.loan,
        sections.recommendation,
        sections.stress_test,
        sections.strategy_comparison,
    )
    missing = tuple(
        dict.fromkeys(
            result.missing_inputs
            + tuple(
                item
                for section in section_values
                for item in section.missing_inputs
            )
        )
    )
    sources = tuple(
        dict.fromkeys(
            result.policy_sources
            + tuple(
                item
                for section in section_values
                for item in section.policy_sources
            )
        )
    )
    return ReportAIInput(
        source_schema_version=result.schema_version,
        simulation_id=result.simulation_id,
        as_of=result.as_of,
        user_summary=result.user_summary,
        goal=result.goal,
        sections=sections,
        missing_inputs=missing,
        warnings=result.warnings,
        policy_sources=sources,
    )


__all__ = ["build_report_ai_input", "sanitize_report_facts"]
