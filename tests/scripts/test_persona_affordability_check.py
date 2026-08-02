"""페르소나 구매 가능성 점검의 분류 규칙.

이 스크립트의 출력은 **설계 문서의 실측 근거**로 쓰인다("20명 중 몇 명이 미달인가").
그 숫자가 틀리면 다음 스펙이 잘못된 전제 위에 세워지므로, 스크립트라도 분류
규칙만은 회귀 검사를 둔다(`scripts/`는 `testpaths` 밖이라 여기서 임포트한다).
"""

from decimal import Decimal

import pytest

from app.regulations.mortgage_limits import HousingStatus
from scripts.check_persona_affordability import (
    _housing_status,
    _UnresolvedHousingStatus,
    _usable_equity,
    classify,
)


class _Section:
    def __init__(self, run_status, result):
        self.run_status = run_status
        self.result = result


class _Result:
    def __init__(self, recommendation):
        self.recommendation = recommendation


class _Status:
    def __init__(self, value):
        self.value = value


def _result(*, covers: bool | None, shortfall: str | None):
    from app.schemas.simulation import SectionRunStatus

    primary: dict[str, object] = {}
    if covers is not None:
        primary["covers_required_amount"] = covers
    loan: dict[str, object] = {"status": "PARTIAL", "primary": primary}
    if shortfall is not None:
        loan["funding_shortfall"] = shortfall
    return _Result(_Section(SectionRunStatus.COMPLETED, {"loan": loan}))


# --------------------------------------------------------------------------
# 탐색 잔차를 자금 부족으로 세지 않는다
# --------------------------------------------------------------------------


def test_a_search_residue_is_not_a_funding_gap() -> None:
    """``loan_max``는 이분 탐색이고 ``epsilon``이 100,000원이다.

    필요액이 탐색 상한이면 최대 10만원의 잔차가 남는다. 그 잔차를 미달로 세면
    **필요액을 이미 다 조달한 차주가 미달로 분류된다.** 실제로 유동자산 1.2억
    페르소나가 부족액 61,035원으로 "미달"이 됐는데, 같은 응답의
    ``covers_required_amount``는 ``True``였다.
    """
    verdict, _, shortfall, _ = classify(_result(covers=True, shortfall="61035.15625"))

    assert verdict == "구매가능"
    # 잔차는 지우지 않는다. 판정 근거에서 뺄 뿐 얼마나 남았는지는 보여준다.
    assert shortfall == Decimal("61035.15625")


def test_a_real_gap_is_still_a_shortfall() -> None:
    """완화가 "전부 구매가능"이 되지 않는지 확인한다."""
    verdict, _, shortfall, _ = classify(_result(covers=False, shortfall="111063232"))

    assert verdict == "미달"
    assert shortfall == Decimal("111063232")


def test_a_missing_verdict_is_not_read_as_either_answer() -> None:
    """판정 근거가 없으면 구매가능도 미달도 아니다(§22.1)."""
    verdict, reason, _, _ = classify(_result(covers=None, shortfall="0"))

    assert verdict == "확인불가"
    assert "covers_required_amount" in reason


# --------------------------------------------------------------------------
# 임차보증금 — 표준 API에 없어 프로필로만 온다
# --------------------------------------------------------------------------


def test_the_lease_deposit_counts_toward_equity() -> None:
    """설계서: 누락하면 전세 거주 페르소나의 자기자본이 **억 단위로** 틀린다."""
    equity, note = _usable_equity(
        {"lease_deposit": 20_000_000}, Decimal("120000000")
    )

    assert equity == Decimal("140000000")
    assert "임차보증금" in note


def test_adding_the_deposit_is_recorded_not_silent() -> None:
    """자기자본이 늘면 필요 대출금액이 줄어 계획이 쉬워 보인다. 조용히 더하지 않는다."""
    _, note = _usable_equity({"lease_deposit": 20_000_000}, Decimal(0))

    assert "lease_end_date" in note


def test_no_deposit_leaves_the_equity_and_the_note_untouched() -> None:
    equity, note = _usable_equity({"lease_deposit": 0}, Decimal("500000"))

    assert equity == Decimal("500000")
    assert note == ""


# --------------------------------------------------------------------------
# 주택보유상태 — 하드코딩하면 LTV가 통째로 달라진다
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (
            {"owns_property": False, "is_first_home_buyer": True},
            HousingStatus.FIRST_HOME_BUYER,
        ),
        (
            {"owns_property": False, "is_first_home_buyer": False},
            HousingStatus.NO_HOUSE,
        ),
    ],
)
def test_the_housing_status_comes_from_what_the_persona_said(
    profile: dict,
    expected: HousingStatus,
) -> None:
    """생애최초는 LTV 70%, 무주택은 40%다. 전원에게 생애최초를 박으면 한도가 커진다."""
    assert _housing_status(profile) == expected


def test_an_owner_is_not_forced_into_one_of_the_three_owner_states() -> None:
    """1주택 유지·처분조건부·다주택은 LTV가 서로 다르고, 프로필에 가를 필드가 없다.

    셋 중 아무거나 고르면 그게 곧 추측이다. 확인불가로 넘긴다.
    """
    with pytest.raises(_UnresolvedHousingStatus):
        _housing_status({"owns_property": True, "is_first_home_buyer": False})
