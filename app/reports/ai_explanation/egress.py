"""외부 LLM으로 나가기 직전 페이로드를 검사하는 게이트.

목적:
    보고서 AI 입력이 외부 서비스로 전송되면 되돌릴 수 없다. Gemini API 무료
    등급은 제출한 프롬프트를 검토·학습에 사용할 수 있다고 Google이 약관에
    명시한다. 그래서 **전송 직전에 한 번 더** 식별자류를 찾는다.
기능:
    직렬화된 페이로드를 훑어 계좌번호·주민번호·연락처·토큰처럼 보이는 값을
    찾고, 하나라도 있으면 전송을 거부한다.
근거:
    ``reports/context.py``의 ``_BLOCKED_KEYS``는 **키 이름 정확 일치** 차단목록이라
    ``loan_account_number``·``accountNumber``·``birthdate`` 같은 변형이 통과한다.
    또 ``financial_diagnosis``·``stress_test``·``strategy_comparison`` 구간은 명시적
    허용목록 없이 결과를 통째로 싣는다. 그 구멍을 키 이름이 아니라 **값의 모양**으로
    막는 것이 이 모듈이다. 두 장치는 서로를 대체하지 않는다.

한계:
    값의 모양만 본다. 이름·주소처럼 형태가 자유로운 정보는 잡지 못한다.
    근본적인 해결은 ``context.py``를 허용목록으로 바꾸는 것이며, 이 게이트는
    그때까지의 안전망이자 그 이후의 이중 확인이다.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any


class ReportEgressBlocked(RuntimeError):
    """식별자류가 발견되어 외부 전송을 중단했다."""

    def __init__(self, findings: tuple["EgressFinding", ...]) -> None:
        summary = ", ".join(f"{item.path}({item.kind})" for item in findings)
        super().__init__("개인정보로 보이는 값이 있어 외부 AI 전송을 중단했습니다: " + summary)
        self.findings = findings


@dataclass(frozen=True)
class EgressFinding:
    path: str
    kind: str
    detail: str


@dataclass(frozen=True)
class EgressReport:
    allowed: bool
    findings: tuple[EgressFinding, ...] = field(default_factory=tuple)
    scanned_values: int = 0


# `\b`는 한글 바로 앞에서 깨진다 — 파이썬 정규식에서 한글은 단어 문자이므로
# "2026-07-28까지"의 끝에는 경계가 없다. 그래서 경계 대신 숫자 룩어라운드를 쓴다.
# 이걸 `\b`로 두면 "…원", "…까지"처럼 한글이 붙은 값을 통째로 놓친다.
#
# 주민등록번호: 6자리-7자리. 생년월일과 성별코드 조합이라 형태가 고유하다.
_RRN = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-4]\d{6}(?!\d)")
_PHONE = re.compile(r"(?<!\d)01[016-9]-?\d{3,4}-?\d{4}(?!\d)")
# 마지막 도메인 라벨이 숫자로만 된 값은 이메일이 아니다. 정책 버전
# ``cashflow-policy@1.0.0`` 같은 내부 식별자를 차단하지 않되 일반 이메일과
# 국제화된 문자 도메인은 계속 탐지한다.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.(?!\d+(?:[^\w-]|$))[\w-]+")
# API 키·토큰. 우리가 실수로 프롬프트에 키를 넣는 것도 막는다.
_TOKEN = re.compile(r"(?:AIza[\w-]{20,}|sk-[\w-]{20,}|AQ\.[\w.\-]{20,}|Bearer\s+[\w.\-]{20,})")
# 계좌번호: 하이픈으로 끊긴 숫자 묶음, 또는 하이픈 없는 11자리 이상.
_ACCOUNT = re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?!\d)|(?<!\d)\d{11,16}(?!\d)")
# 날짜는 계좌번호와 형태가 겹친다 — `2026-07-28`이 `\d{2,6}-\d{2,6}-\d{2,8}`에
# 정확히 들어맞는다. 이걸 걸러내지 않으면 `as_of`·`policy_sources`·규제 기준일이
# 전부 계좌번호로 오인돼 **정상 트래픽이 모두 차단된다.** 실제로 그렇게 됐다.
_DATE_LIKE = re.compile(r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)")
# UUID도 같은 이유로 겹친다 — 숫자만 담긴 UUID의 가운데 토막이
# `\d{2,6}-\d{2,6}-\d{2,8}`에 들어맞는다. 매물 검색 스냅샷 식별자가 여기 걸려
# **매물 보고서 전체가 AI에 나가지 못했다.** 8-4-4-4-12 16진수는 계좌번호가
# 갖는 형태가 아니므로 날짜와 같이 지우고 본다.
_UUID_LIKE = re.compile(
    r"(?<![\w-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![\w-])"
)

# 판정 순서가 중요하다. 휴대전화번호(010-1234-5678)는 계좌번호 형태에도 들어맞으므로
# 더 구체적인 패턴을 먼저 본다 — 첫 일치에서 멈추기 때문이다.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("resident_registration_number", _RRN, "주민등록번호 형태입니다."),
    ("phone_number", _PHONE, "휴대전화번호 형태입니다."),
    ("email", _EMAIL, "이메일 주소 형태입니다."),
    ("credential", _TOKEN, "API 키 또는 토큰 형태입니다."),
    ("account_number", _ACCOUNT, "계좌번호 형태의 숫자입니다."),
)

# 금액·비율은 숫자 그대로 저장되므로 계좌번호 정규식에 걸릴 수 있다. 금액이
# 들어가는 것으로 확인된 키는 숫자 검사에서 제외한다. **키를 늘릴 때는 그 값이
# 정말 금액인지 확인할 것** — 여기 넣으면 그 경로는 계좌번호 검사를 통과한다.
_NUMERIC_VALUE_KEYS = frozenset(
    {
        "amount",
        "annual_income",
        "monthly_income",
        "monthly_expense",
        "liquid_assets",
        "housing_assets",
        "total_debt",
        "monthly_debt_payment",
        "emergency_reserve",
        "target_amount",
        "monthly_rent",
        "management_fee",
        "maximum_amount",
        "recommended_amount",
        "required_amount",
        "monthly_payment",
        "total_interest",
        "total_financial_cost",
        "expected_maturity_amount",
        "expected_net_interest",
        "allocation_amount",
        "funding_shortfall",
        "product_minimum_amount",
        "buffer_target",
        "simulation_id",
    }
)


def _walk(value: object, path: str = "") -> Iterator[tuple[str, str, object]]:
    """(경로, 마지막 키, 값)을 훑는다."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, path.rsplit(".", 1)[-1].split("[", 1)[0], value


def scan_payload(payload: dict[str, Any]) -> EgressReport:
    """전송 후보 페이로드에서 식별자류를 찾는다."""
    findings: list[EgressFinding] = []
    scanned = 0
    for path, key, value in _walk(payload):
        if value is None or isinstance(value, bool):
            continue
        text = str(value)
        scanned += 1
        for kind, pattern, detail in _PATTERNS:
            target = text
            if kind == "account_number":
                if key in _NUMERIC_VALUE_KEYS:
                    # 금액 필드의 큰 정수는 계좌번호가 아니다.
                    continue
                # 날짜와 UUID를 지운 뒤에 본다. 지우지 않으면 기준일·시행일과
                # 산출 식별자가 모두 계좌번호로 잡힌다.
                target = _UUID_LIKE.sub(" ", _DATE_LIKE.sub(" ", text))
            if pattern.search(target):
                findings.append(EgressFinding(path=path, kind=kind, detail=detail))
                break
    return EgressReport(
        allowed=not findings,
        findings=tuple(findings),
        scanned_values=scanned,
    )


def guard_payload(payload: dict[str, Any], *, enabled: bool = True) -> EgressReport:
    """전송을 허용할지 판단한다. 막히면 예외를 던져 조용히 나가지 못하게 한다."""
    report = scan_payload(payload)
    if not enabled:
        return report
    if not report.allowed:
        raise ReportEgressBlocked(report.findings)
    return report


__all__ = [
    "EgressFinding",
    "EgressReport",
    "ReportEgressBlocked",
    "guard_payload",
    "scan_payload",
]
