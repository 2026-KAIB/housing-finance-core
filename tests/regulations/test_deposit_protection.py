from datetime import date
from decimal import Decimal

import pytest

from app.regulations.deposit_protection import (
    DEPOSIT_PROTECTION_HISTORY,
    get_deposit_protection_limit,
    resolve_deposit_protection_limit,
)

_TODAY = date(2026, 7, 29)


class TestCurrentLimit:
    def test_today_is_one_hundred_million(self) -> None:
        assert resolve_deposit_protection_limit(as_of=_TODAY) == Decimal("100000000")

    def test_the_source_is_recorded(self) -> None:
        limit = get_deposit_protection_limit(as_of=_TODAY)
        assert limit is not None
        assert limit.source
        assert limit.verified is True


class TestEffectiveDates:
    """시행일 경계. 값 하나에 시행일만 달아 두면 낡은 값이 계속 조회된다."""

    def test_the_day_before_the_raise_is_still_fifty_million(self) -> None:
        assert resolve_deposit_protection_limit(as_of=date(2025, 8, 31)) == Decimal(
            "50000000"
        )

    def test_the_effective_day_itself_is_one_hundred_million(self) -> None:
        assert resolve_deposit_protection_limit(as_of=date(2025, 9, 1)) == Decimal(
            "100000000"
        )

    def test_the_superseded_value_stops_applying(self) -> None:
        # 종전 한도는 끝나는 날이 있어야 새 고시 이후로 새어 나오지 않는다.
        old = DEPOSIT_PROTECTION_HISTORY[0]
        assert old.amount == Decimal("50000000")
        assert old.effective_to == date(2025, 8, 31)
        assert old.covers(date(2025, 9, 1)) is False

    def test_intervals_do_not_overlap_or_leave_gaps(self) -> None:
        for earlier, later in zip(
            DEPOSIT_PROTECTION_HISTORY, DEPOSIT_PROTECTION_HISTORY[1:], strict=False
        ):
            assert earlier.effective_to is not None, "마지막 구간을 뺀 나머지는 끝나야 한다"
            assert (later.effective_from - earlier.effective_to).days == 1

    def test_the_last_interval_stays_open(self) -> None:
        assert DEPOSIT_PROTECTION_HISTORY[-1].effective_to is None


class TestUnknownIsNotAGuess:
    """확정하지 못한 한도를 임의의 숫자로 대체하면 양방향으로 틀린다.

    낮게 잡으면 멀쩡한 상품이 부적격으로 탈락하고, 높게 잡으면 보호받지 못하는
    금액을 보호받는다고 보고한다.
    """

    def test_a_date_before_any_interval_is_unresolved(self) -> None:
        assert get_deposit_protection_limit(as_of=date(1999, 1, 1)) is None

    def test_resolve_refuses_instead_of_falling_back(self) -> None:
        with pytest.raises(ValueError, match="확정할 수 없습니다"):
            resolve_deposit_protection_limit(as_of=date(1999, 1, 1))
