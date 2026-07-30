"""SSOT §19가 정한 6개 항목의 고정 양식 보고서.

목적:
    보고서의 **구조와 수치를 우리가 확정하고**, AI에게는 각 항목의 서술 칸만
    맡긴다. 자유 서술을 받으면 AI가 수치를 인용하다 귀속을 틀린다 — 실제로
    "목표 금액 대비 66,479,492원 부족"(실은 필요 대출금액 대비)이 나왔고,
    값이 페이로드에 있었기 때문에 숫자 검증기는 통과시켰다.

기능:
    ``FormSection.figures``는 이 모듈이 계산 결과에서 렌더링한 수치 줄이다.
    ``narration``은 AI가 채우는 칸이며 **수치를 쓸 수 없다**(검증기가 막는다).
근거:
    SSOT §19의 여섯 항목을 절 순서로 고정한다. 항목이 계산되지 않았으면 빈 칸이
    아니라 "무엇이 없어서 계산하지 못했다"를 적는다(§22.1 UNKNOWN 계약).
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.schemas.report import ReportAIInput, ReportSection
from app.schemas.simulation import SectionRunStatus

# (키, 절 제목). SSOT §19의 나열 순서를 그대로 쓴다.
FORM_SECTIONS: tuple[tuple[str, str], ...] = (
    ("decision_reasons", "1. 추천·탈락 사유"),
    ("rates_and_policy", "2. 사용 금리와 정책 기준일"),
    ("preferential_rate", "3. 우대조건 예상 달성률"),
    ("base_vs_stress", "4. 기본 조건과 스트레스 조건의 차이"),
    ("shortfall_and_extension", "5. 목표 미달 시 필요한 보완"),
    ("user_confirmations", "6. 사용자가 직접 확인할 조건"),
)

_NOT_CALCULATED = "아직 계산하지 않았습니다."

_GOAL_LABELS: dict[str, str] = {
    "HOME_PURCHASE": "주택 구입",
    "JEONSE_DEPOSIT": "전세 보증금",
    "MONTHLY_RENT_DEPOSIT": "월세 보증금",
}

# 결측 필드명을 사용자가 읽을 말로 바꾼다. **없는 키는 원래 이름을 그대로 보여준다** —
# 모르는 결측을 숨기면 "확인할 것이 없다"로 읽혀 UNKNOWN 계약을 어기게 된다.
_MISSING_LABELS: dict[str, str] = {
    "loan_request": "대출 계산에 필요한 만기·주택보유상태·필수생활비",
    "regulation_region": "주택 소재지의 규제지역 구분",
    "loan_product_candidates": "비교할 대출 상품 목록",
    "recommended_loan_option": "추천 대출 옵션",
    "ltv_ratio": "해당 조건의 LTV 비율(1차 출처 미확인)",
    "dti_ratio": "해당 지역의 DTI 비율",
    "stress_dsr_rate": "스트레스 DSR 가산금리",
    "product_limit_amount": "상품별 대출 한도",
    "dti_limit_amount": "DTI 환산 한도",
    "annual_rate": "상품 금리",
    "total_cost": "대출 부대비용(보증료·수수료 등) 총액",
    "repayment_flexibility": "중도상환 조건 등 상환 유연성",
    "savings_policy_validation": "예·적금 상품정책 재검증 결과",
    "verified_savings_maturity_amount": "검증된 예·적금 예상 만기액",
    "monthly_savings_commitment": "월 적금 납입 계획 금액",
    "interest_rate_shock_applicability": "금리 유형(고정·변동·혼합)과 고정기간",
    "future_loan_capacity": "미래 시점의 대출 계획 한도",
    "available_equity": "구매 시점에 쓸 수 있는 자기자본",
}


def _missing_label(name: str) -> str:
    label = _MISSING_LABELS.get(name)
    return f"{label} ({name})" if label else name


@dataclass(frozen=True)
class FormSection:
    key: str
    title: str
    # 엔진이 렌더링한 수치 줄. AI가 손대지 않는다.
    figures: tuple[str, ...] = field(default_factory=tuple)
    # AI가 채우는 서술 칸. 수치를 넣을 수 없다.
    narration: str | None = None


@dataclass(frozen=True)
class ReportForm:
    headline: str
    sections: tuple[FormSection, ...]
    policy_sources: tuple[str, ...] = field(default_factory=tuple)
    disclaimers: tuple[str, ...] = (
        "이 보고서는 계산 결과를 설명한 것이며 대출 승인이나 실제 적용금리를 보장하지 않습니다.",
        "UNKNOWN과 결측은 실패나 0이 아니며, 확인하면 결과가 달라질 수 있습니다.",
        "수치는 계산 엔진이 산출했고 문장 설명만 AI가 작성했습니다.",
    )

    def section(self, key: str) -> FormSection | None:
        return next((item for item in self.sections if item.key == key), None)

    def to_text(self) -> str:
        parts = [self.headline, ""]
        for item in self.sections:
            parts.append(f"## {item.title}")
            parts.extend(item.figures or (_NOT_CALCULATED,))
            if item.narration:
                parts.extend(["", item.narration.strip()])
            parts.append("")
        if self.policy_sources:
            parts.append("## 근거 출처")
            parts.extend(f"- {source}" for source in self.policy_sources)
            parts.append("")
        parts.append("## 유의사항")
        parts.extend(f"- {note}" for note in self.disclaimers)
        return "\n".join(parts).strip()


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _won(value: object) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return str(value)
    # 원 단위 정수로 내린다. 이분탐색 결과의 소수점을 그대로 보이면 안 된다.
    return f"{int(parsed):,}원"


def _percent(value: object) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return str(value)
    return f"{parsed * 100:.2f}%"


def _facts(section: ReportSection) -> dict[str, object]:
    if section.run_status is SectionRunStatus.NOT_RUN or not section.facts:
        return {}
    return dict(section.facts)


def _primary(payload: ReportAIInput) -> dict[str, object]:
    primary = _facts(payload.sections.loan).get("primary")
    return dict(primary) if isinstance(primary, dict) else {}


def _decision_reasons(payload: ReportAIInput) -> tuple[str, ...]:
    loan = _facts(payload.sections.loan)
    if not loan:
        lines = [_NOT_CALCULATED]
        lines.extend(f"- {reason}" for reason in payload.sections.loan.reasons)
        return tuple(lines)

    lines: list[str] = [f"- 대출 구간 상태: {loan.get('status', '알 수 없음')}"]
    primary = _primary(payload)
    if primary:
        lines.append(
            f"- 추천 1순위: {primary.get('product_name')} / {primary.get('option_name')}"
        )
        lines.append(f"- 계산된 대출 가능액: {_won(primary.get('maximum_amount'))}")
    for count_key, label in (
        ("rejected_count", "자격 탈락"),
        ("unresolved_count", "입력 부족으로 계산 보류"),
    ):
        value = loan.get(count_key)
        if isinstance(value, int) and value:
            lines.append(f"- {label}: {value}건")
    lines.extend(f"- {reason}" for reason in payload.sections.loan.reasons)
    return tuple(lines)


def _rates_and_policy(payload: ReportAIInput) -> tuple[str, ...]:
    primary = _primary(payload)
    loan_facts = _facts(payload.sections.loan)
    lines: list[str] = [f"- 계산 기준일: {payload.as_of.isoformat()}"]
    policy_as_of = loan_facts.get("policy_as_of")
    if policy_as_of:
        lines.append(f"- 적용 규제 기준일: {policy_as_of}")
    if not primary:
        lines.append(f"- 금리: {_NOT_CALCULATED}")
        return tuple(lines)
    lines.append(f"- 실제 적용 금리(상환액 계산): 연 {_percent(primary.get('annual_rate'))}")
    assessment = primary.get("assessment_annual_rate")
    if assessment is not None:
        lines.append(
            f"- 심사용 금리(스트레스 DSR 판정): 연 {_percent(assessment)} "
            "— 실제로 내는 금리가 아닙니다."
        )
    lines.append(f"- 월 상환액(실제 금리 기준): {_won(primary.get('monthly_payment'))}")
    return tuple(lines)


def _preferential_rate(payload: ReportAIInput) -> tuple[str, ...]:
    savings = _facts(payload.sections.savings)
    if not savings:
        return (
            _NOT_CALCULATED,
            "- 우대금리 달성률은 예·적금 포트폴리오가 계산된 뒤에 산출됩니다.",
            f"- 예·적금 구간 상태: {payload.sections.savings.engine_status or '미실행'}",
        )
    lines: list[str] = []
    allocations = savings.get("allocations")
    if isinstance(allocations, list) and allocations:
        for item in allocations:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('product_name')}: 배분 {_won(item.get('allocation_amount'))}, "
                f"예상 만기 {_won(item.get('expected_maturity_amount'))}"
            )
    else:
        lines.append("- 배분된 예·적금 상품이 없습니다.")
    return tuple(lines)


def _base_vs_stress(payload: ReportAIInput) -> tuple[str, ...]:
    primary = _primary(payload)
    stress = _facts(payload.sections.stress_test)
    if not primary and not stress:
        return (_NOT_CALCULATED,)

    lines: list[str] = []
    if primary:
        lines.append(f"- 기본 조건 예상 DSR: {_percent(primary.get('expected_dsr'))}")
        lines.append(f"- 기본 조건 월 상환액: {_won(primary.get('monthly_payment'))}")
    if not stress:
        lines.append(f"- 스트레스 결과: {_NOT_CALCULATED}")
        return tuple(lines)

    lines.append(
        f"- 스트레스 시나리오: 총 {_scenario_total(stress)}개 중 "
        f"PASS {stress.get('pass_count')} / FAIL {stress.get('fail_count')} / "
        f"UNKNOWN {stress.get('unknown_count')}"
    )
    if stress.get("maximum_dsr") is not None:
        lines.append(f"- 최악 시나리오 예상 DSR: {_percent(stress.get('maximum_dsr'))}")
    worst = _worst_scenario(stress)
    if worst:
        lines.append(
            f"- 최초 실패 시나리오: {worst.get('name')} "
            f"(적용 금리 연 {_percent(worst.get('applied_annual_rate'))}, "
            f"월 상환액 {_won(worst.get('monthly_payment'))})"
        )
    margin = stress.get("minimum_buffer_margin")
    if margin is not None:
        parsed = _decimal(margin)
        if parsed is not None and parsed < 0:
            lines.append(f"- 최소 여유자금 부족액: {_won(abs(parsed))}")
    return tuple(lines)


def _scenario_total(stress: dict[str, object]) -> int:
    scenarios = stress.get("scenarios")
    return len(scenarios) if isinstance(scenarios, list) else 0


def _worst_scenario(stress: dict[str, object]) -> dict[str, object]:
    code = stress.get("first_failed_scenario")
    scenarios = stress.get("scenarios")
    if not code or not isinstance(scenarios, list):
        return {}
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        scenario = item.get("scenario")
        if isinstance(scenario, dict) and scenario.get("code") == code:
            return {
                "name": scenario.get("name"),
                "applied_annual_rate": item.get("applied_annual_rate"),
                "monthly_payment": item.get("monthly_payment"),
            }
    return {}


def _shortfall_and_extension(payload: ReportAIInput) -> tuple[str, ...]:
    loan = _facts(payload.sections.loan)
    strategy = _facts(payload.sections.strategy_comparison)
    lines: list[str] = []
    if loan:
        required = loan.get("required_amount")
        shortfall = loan.get("funding_shortfall")
        lines.append(f"- 필요 대출금액: {_won(required)}")
        lines.append(f"- 계산된 최대 조달액: {_won(loan.get('maximum_recommendable_amount'))}")
        parsed = _decimal(shortfall)
        if parsed is not None and parsed > 0:
            # 부족액의 기준을 문장에 박아 둔다. AI가 "목표 금액 대비"로 잘못
            # 귀속했던 자리다.
            lines.append(f"- **필요 대출금액 대비** 부족액: {_won(parsed)}")
        else:
            lines.append("- 필요 대출금액을 계산된 한도 안에서 충당할 수 있습니다.")
    else:
        lines.append(f"- 대출 조달: {_NOT_CALCULATED}")

    if strategy:
        lines.append(f"- 전략 비교 상태: {strategy.get('status')}")
    else:
        lines.append(
            "- 목표 시점 연장 폭은 자산축적형 전략 비교가 계산된 뒤에 산출됩니다."
        )
    return tuple(lines)


def _user_confirmations(payload: ReportAIInput) -> tuple[str, ...]:
    lines: list[str] = []
    if payload.missing_inputs:
        lines.append("확인이 필요한 입력:")
        lines.extend(f"- {_missing_label(name)}" for name in payload.missing_inputs)
        lines.append("")
    assumptions = tuple(
        note
        for section in (
            payload.sections.loan,
            payload.sections.savings,
            payload.sections.recommendation,
        )
        for note in section.reasons
        if "가정" in note or "파생" in note or "같다고" in note
    )
    if assumptions:
        lines.append("계산에 사용한 가정:")
        lines.extend(f"- {note}" for note in dict.fromkeys(assumptions))
        lines.append("")
    lines.append("상품 설명서에서 직접 확인할 것:")
    lines.append("- 우대금리 조건과 그 달성 가능성")
    lines.append("- 자유텍스트로만 적힌 자격 세부조건(직업·거래실적 등)")
    return tuple(lines)


_BUILDERS = {
    "decision_reasons": _decision_reasons,
    "rates_and_policy": _rates_and_policy,
    "preferential_rate": _preferential_rate,
    "base_vs_stress": _base_vs_stress,
    "shortfall_and_extension": _shortfall_and_extension,
    "user_confirmations": _user_confirmations,
}


def build_report_form(
    payload: ReportAIInput,
    *,
    narrations: dict[str, str] | None = None,
) -> ReportForm:
    """수치를 확정한 고정 양식을 만든다. ``narrations``가 있으면 서술 칸을 채운다."""
    resolved = narrations or {}
    goal = payload.goal
    headline = (
        f"# 주택자금 계획 보고서\n"
        f"- 기준일: {payload.as_of.isoformat()}\n"
        f"- 목표: {_GOAL_LABELS.get(goal.goal_type.value, goal.goal_type.value)} "
        f"{_won(goal.target_amount)} ({goal.target_date.isoformat()}까지)"
    )
    sections = tuple(
        FormSection(
            key=key,
            title=title,
            figures=_BUILDERS[key](payload),
            narration=resolved.get(key),
        )
        for key, title in FORM_SECTIONS
    )
    return ReportForm(
        headline=headline,
        sections=sections,
        policy_sources=payload.policy_sources,
    )


__all__ = ["FORM_SECTIONS", "FormSection", "ReportForm", "build_report_form"]
