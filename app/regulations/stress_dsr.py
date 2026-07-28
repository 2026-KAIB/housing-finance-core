from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

# 스트레스 DSR — DSR을 **실제 대출금리가 아니라 "실제 금리 + 가산금리"로 산정**하는
# 규제다. 금리 상승 국면에서 상환 부담이 커질 것을 미리 반영하는 장치이며,
# **심사 기준에만 적용되고 실제 대출금리에는 영향을 주지 않는다.**
#
# 이 구분이 이 모듈의 핵심이다. 대출가능액 계산에서 금리가 두 번 쓰이는데
# 서로 다른 값이어야 한다:
#
#   DSR 판정      → 실제 금리 + 스트레스 금리   (규제가 요구하는 심사 기준)
#   월 현금흐름    → 실제 금리                  (차주가 실제로 내는 돈)
#
# 하나로 뭉치면 어느 쪽으로 뭉치든 틀린다. 실제 금리로 DSR을 보면 한도가
# 과대평가되고(연소득 6천만·30년·4% 기준 약 28%), 스트레스 금리로 현금흐름을
# 보면 실제보다 빠듯하게 나온다.
#
# 1차 출처
#   [KB]    KB국민은행 「스트레스 DSR 3단계 시행, 대출 한도 얼만큼 줄었을까」
#           https://kbthink.com/loan/borrow-guide/stressdsr.html
#           "실제대출금리에 스트레스 금리를 가산한 기준으로 DSR을 산정",
#           3단계 시행 2025-07-01, 수도권·규제지역 주담대 3.00%(2025-10-16~),
#           지방 주담대 0.75%, 주담대 외 1.50%(신용대출은 잔액 1억 초과 시),
#           일반 하한 1.50% 상한 3.00% / 수도권·규제지역은 하한 3.00% 상한 없음
#   [10·15] 「주택시장 안정화를 위한 대출수요 관리 방안」(2025-10-15, 시행 10-16)
#           수도권·규제지역 스트레스 금리 하한 1.5% → 3.0%
#           (`mortgage_limits.MORTGAGE_HARD_CAP_EFFECTIVE_FROM`과 같은 시행일이다)


class StressRegion(StrEnum):
    """스트레스 가산금리를 가르는 지역 구분.

    `mortgage_limits.RegulationZone`(LTV용)과 별개인 이유는 기준이 다르기
    때문이다 — LTV는 투기과열/조정대상/비규제 3분이지만, 스트레스 금리는
    **수도권이거나 규제지역이면** 한 묶음이고 나머지가 지방이다.
    비규제지역이어도 수도권이면 3.00%가 적용된다.
    """

    CAPITAL_OR_REGULATED = "CAPITAL_OR_REGULATED"  # 수도권 또는 규제지역
    LOCAL = "LOCAL"  # 그 외 지방


class StressLoanKind(StrEnum):
    """스트레스 금리가 다르게 붙는 대출 종류."""

    MORTGAGE = "MORTGAGE"  # 주택담보대출
    CREDIT = "CREDIT"  # 신용대출 — 잔액 1억 초과 시에만 적용
    OTHER = "OTHER"  # 그 밖의 주담대 외 대출


@dataclass(frozen=True)
class StressRate:
    """출처가 붙은 스트레스 가산금리 하나.

    `rate`는 실제 금리에 **더할** 값이다(0.03 = 3.00%p). 0은 "적용되지 않음"을
    뜻하며 "모름"이 아니다 — 모르면 조회가 None을 반환한다.
    """

    rate: Decimal
    source: str
    effective_from: date
    effective_to: date | None = None
    verified: bool = True
    note: str | None = None

    def covers(self, as_of: date) -> bool:
        if as_of < self.effective_from:
            return False
        return self.effective_to is None or as_of <= self.effective_to


_KB = "KB국민은행 「스트레스 DSR 3단계」 안내(kbthink.com/loan/borrow-guide/stressdsr.html)"
_TEN_FIFTEEN = "「주택시장 안정화를 위한 대출수요 관리 방안」(2025-10-15, 시행 2025-10-16)"

# 3단계 시행일. 이 날 이전 구간(1·2단계)의 값은 이 표에 없다.
STRESS_DSR_PHASE3_FROM = date(2025, 7, 1)

# 일반 하한·상한. 스트레스 금리는 원래 "과거 5년 내 최고금리와 현재 금리의 차"로
# 산정하되 이 범위로 자른다. 아래 표의 값은 그렇게 확정된 적용치다.
STRESS_RATE_FLOOR = Decimal("0.015")
STRESS_RATE_CEILING = Decimal("0.030")

# 신용대출에 스트레스 금리가 붙기 시작하는 잔액 기준.
CREDIT_LOAN_STRESS_THRESHOLD = Decimal("100000000")

STRESS_RATE_HISTORY: dict[tuple[StressRegion, StressLoanKind], tuple[StressRate, ...]] = {
    (StressRegion.CAPITAL_OR_REGULATED, StressLoanKind.MORTGAGE): (
        StressRate(
            rate=Decimal("0.030"),
            source=f"{_TEN_FIFTEEN}; {_KB}",
            effective_from=date(2025, 10, 16),
            note="수도권·규제지역 주담대는 하한 3.00%이며 상한 제한이 없다.",
        ),
    ),
    (StressRegion.LOCAL, StressLoanKind.MORTGAGE): (
        StressRate(
            rate=Decimal("0.0075"),
            source=_KB,
            effective_from=STRESS_DSR_PHASE3_FROM,
            note="지방 주담대 0.75%. 2026년 상반기까지 유지 후 조정 예정으로 안내됨.",
        ),
    ),
    (StressRegion.CAPITAL_OR_REGULATED, StressLoanKind.CREDIT): (
        StressRate(
            rate=Decimal("0.015"),
            source=_KB,
            effective_from=STRESS_DSR_PHASE3_FROM,
            note="주담대 외 1.50%. 신용대출은 잔액 1억원 초과분에 한해 적용.",
        ),
    ),
    (StressRegion.LOCAL, StressLoanKind.CREDIT): (
        StressRate(
            rate=Decimal("0.015"),
            source=_KB,
            effective_from=STRESS_DSR_PHASE3_FROM,
            note="주담대 외 1.50%. 신용대출은 잔액 1억원 초과분에 한해 적용.",
        ),
    ),
    (StressRegion.CAPITAL_OR_REGULATED, StressLoanKind.OTHER): (
        StressRate(
            rate=Decimal("0.015"),
            source=_KB,
            effective_from=STRESS_DSR_PHASE3_FROM,
            verified=False,
            note=(
                "출처는 '주담대 외 1.5%'라고만 하며 전세자금대출 등 개별 상품의 "
                "취급을 명시하지 않는다. 전세대출은 원금이 DSR에 산입되지 않는 등 "
                "취급이 다를 수 있어 1차 출처 확인 전까지 사용 금지."
            ),
        ),
    ),
    (StressRegion.LOCAL, StressLoanKind.OTHER): (
        StressRate(
            rate=Decimal("0.015"),
            source=_KB,
            effective_from=STRESS_DSR_PHASE3_FROM,
            verified=False,
            note="위와 동일한 사유로 미검증.",
        ),
    ),
}


def resolve_stress_region(*, is_capital_region: bool, is_regulated_region: bool) -> StressRegion:
    """수도권이거나 규제지역이면 강한 쪽 구분을 쓴다."""
    if is_capital_region or is_regulated_region:
        return StressRegion.CAPITAL_OR_REGULATED
    return StressRegion.LOCAL


def get_stress_rate(
    region: StressRegion,
    kind: StressLoanKind,
    *,
    as_of: date,
    credit_loan_balance: Decimal | None = None,
    allow_unverified: bool = False,
) -> StressRate | None:
    """`as_of` 시점에 적용되는 스트레스 가산금리를 찾는다.

    표에 없거나, 그 시점을 덮는 구간이 없거나, 미검증 값이면 None이다 —
    "가산금리를 모른다"를 0으로 뭉개면 한도가 과대평가되므로 절대 0으로
    대체하지 않는다.

    신용대출은 잔액이 1억원을 넘을 때만 적용된다. 잔액을 모르면 판단할 수 없어
    None이고, 1억원 이하이면 **0%가 확정**이므로 rate=0인 값을 돌려준다.
    """
    if kind is StressLoanKind.CREDIT:
        if credit_loan_balance is None:
            return None
        if credit_loan_balance <= CREDIT_LOAN_STRESS_THRESHOLD:
            return StressRate(
                rate=Decimal("0"),
                source=_KB,
                effective_from=STRESS_DSR_PHASE3_FROM,
                note=(
                    f"신용대출 잔액 {credit_loan_balance:,.0f}원이 "
                    f"{CREDIT_LOAN_STRESS_THRESHOLD:,.0f}원 이하라 스트레스 금리 미적용"
                ),
            )

    history = STRESS_RATE_HISTORY.get((region, kind))
    if not history:
        return None
    for rate in history:
        if not rate.covers(as_of):
            continue
        if not rate.verified and not allow_unverified:
            return None
        return rate
    return None


def stressed_annual_rate(annual_rate: Decimal, stress: StressRate) -> Decimal:
    """DSR 심사에 쓸 금리 = 실제 금리 + 가산금리.

    반환값을 상환액 계산에 쓰면 안 된다 — 차주가 실제로 내는 돈은 `annual_rate`
    기준이다(출처: "실제 대출금리에는 영향을 주지 않습니다").
    """
    if annual_rate < 0:
        raise ValueError(f"annual_rate는 음수일 수 없습니다: {annual_rate}")
    return annual_rate + stress.rate
