from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# 예금자보호 한도표다. 예적금 평가(`engines/savings/evaluation.py`)와 포트폴리오
# 배분(`engines/savings/portfolio.py`)이 쓰는 `deposit_protection_limit`의 공급원이다.
#
# 이 값은 은행이 정하는 것이 아니라 예금자보호법·시행령이 정하는 **규제 상수**다.
# 그래서 LTV·DTI(`regulations/mortgage_limits.py`)와 같은 규율을 따른다 —
# 출처와 시행기간을 함께 들고 다니고, 기준일을 넘겨 조회한다. 값 하나에 시행일만
# 달아 두면 낡은 값이 새 고시 이후에도 계속 조회된다(§22.4에서 조정대상지역
# LTV 50%가 실제로 그렇게 살아남았다).
#
# 순수 계산 계층(engines/savings/*)은 이 모듈을 import하지 않는다. 한도는 호출자가
# 여기서 기준일로 구해 입력으로 넘긴다. 대출 쪽에서 서비스 계층이 규제표를 읽어
# `PolicyLimits`를 만들어 넘기는 것과 같은 구조다.
#
# 1차 출처
#   [25·9·1] 금융위원회 「예금보호한도 상향 시행('25.9.1일) 준비상황 점검」
#            https://www.fsc.go.kr/no010101/85114
#            예금자보호법 개정에 따라 2025-09-01부터 보호한도 5천만원 → 1억원.
#            가입 시점과 무관하게 적용되며 별도 신청이 필요 없다.


@dataclass(frozen=True)
class DepositProtectionLimit:
    """출처가 붙은 예금자보호 한도 하나.

    `effective_to`는 이 한도가 **마지막으로 적용되는 날**(포함)이며, None이면
    아직 유효하다.
    """

    amount: Decimal
    source: str
    effective_from: date
    effective_to: date | None = None
    verified: bool = True
    note: str | None = None

    def covers(self, as_of: date) -> bool:
        if as_of < self.effective_from:
            return False
        return self.effective_to is None or as_of <= self.effective_to


_FSC_2025 = "금융위 「예금보호한도 상향 시행('25.9.1일) 준비상황 점검」 (2025)"
_PRE_2025 = "예금자보호법 시행령(2001-01-01 시행 5천만원)"

# 최신 구간이 앞에 오도록 선언하지 않는다 — 조회는 `covers()`로 하므로 순서와
# 무관하다. 시간순으로 읽히도록 오래된 것부터 둔다.
DEPOSIT_PROTECTION_HISTORY: tuple[DepositProtectionLimit, ...] = (
    DepositProtectionLimit(
        amount=Decimal("50000000"),
        source=_PRE_2025,
        effective_from=date(2001, 1, 1),
        effective_to=date(2025, 8, 31),
        note="종전 한도 5천만원",
    ),
    DepositProtectionLimit(
        amount=Decimal("100000000"),
        source=_FSC_2025,
        effective_from=date(2025, 9, 1),
        note="2025-09-01 상향. 가입 시점과 무관하게 적용된다.",
    ),
)


def get_deposit_protection_limit(
    *,
    as_of: date,
    allow_unverified: bool = False,
) -> DepositProtectionLimit | None:
    """`as_of` 시점에 적용되는 예금자보호 한도. 확정하지 못하면 None.

    None을 임의의 숫자로 대체하면 안 된다. 한도를 낮게 잡으면 멀쩡한 상품이
    부적격으로 탈락하고, 높게 잡으면 보호받지 못하는 금액을 보호받는다고
    보고하게 된다 — 양방향으로 틀린다.
    """
    for limit in DEPOSIT_PROTECTION_HISTORY:
        if not limit.covers(as_of):
            continue
        if not limit.verified and not allow_unverified:
            return None
        return limit
    return None


def resolve_deposit_protection_limit(
    *,
    as_of: date,
    allow_unverified: bool = False,
) -> Decimal:
    """금액만 필요한 호출부를 위한 편의 함수. 확정하지 못하면 `ValueError`.

    조용히 기본값으로 넘어가지 않는다 — 이 상수를 스크립트 기본값 리터럴로
    두었더니 2025-09-01 상향을 11개월 동안 아무도 알아채지 못했다.
    """
    limit = get_deposit_protection_limit(as_of=as_of, allow_unverified=allow_unverified)
    if limit is None:
        raise ValueError(
            f"{as_of.isoformat()} 기준의 예금자보호 한도를 확정할 수 없습니다. "
            "DEPOSIT_PROTECTION_HISTORY에 해당 시점을 덮는 구간이 없습니다."
        )
    return limit.amount
