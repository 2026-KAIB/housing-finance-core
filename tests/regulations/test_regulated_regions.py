from datetime import date

from app.regulations.mortgage_limits import RegulationZone
from app.regulations.regulated_regions import (
    DESIGNATION_LIST_VERIFIED_THROUGH,
    DESIGNATIONS_WITHOUT_CODE,
    REGION_DESIGNATIONS,
    is_capital_region_code,
    is_valid_region_code,
    resolve_region,
)

_TODAY = date(2026, 7, 28)


class TestDesignatedRegions:
    def test_all_seoul_districts_are_regulated(self) -> None:
        # 10·15로 서울 25개 자치구 전역이 지정됐다.
        seoul = [row for row in REGION_DESIGNATIONS if row.sido == "서울특별시"]
        assert len(seoul) == 25
        for row in seoul:
            resolved = resolve_region(as_of=_TODAY, region_code=row.code)
            assert resolved.zone is RegulationZone.SPECULATION_OVERHEATED, row.name

    def test_gangnam_is_regulated_and_capital(self) -> None:
        resolved = resolve_region(as_of=_TODAY, region_code="11680")
        assert resolved.zone is RegulationZone.SPECULATION_OVERHEATED
        assert resolved.is_capital_region is True
        assert resolved.name == "강남구"
        assert resolved.sources

    def test_bundang_is_regulated(self) -> None:
        resolved = resolve_region(as_of=_TODAY, region_code="41135")
        assert resolved.zone is RegulationZone.SPECULATION_OVERHEATED
        assert resolved.name == "성남시 분당구"

    def test_designations_are_all_speculation_overheated_today(self) -> None:
        # 현재 지정된 지역은 전부 투기과열지구·조정대상지역 동시 지정이라
        # 더 강한 쪽으로 해석된다. 조정대상 단독 지정 목록은 비어 있다.
        assert all(
            row.zone is RegulationZone.SPECULATION_OVERHEATED for row in REGION_DESIGNATIONS
        )


class TestEffectiveDates:
    def test_july_2026_additions_are_not_regulated_before_their_date(self) -> None:
        # 구리시는 2026-07-01부터 지정 효력이 발생한다.
        before = resolve_region(as_of=date(2026, 6, 30), region_code="41310")
        after = resolve_region(as_of=date(2026, 7, 1), region_code="41310")
        assert before.zone is RegulationZone.NON_REGULATED
        assert after.zone is RegulationZone.SPECULATION_OVERHEATED

    def test_seoul_is_not_regulated_before_october_2025(self) -> None:
        before = resolve_region(as_of=date(2025, 10, 15), region_code="11350")
        assert before.zone is RegulationZone.NON_REGULATED


class TestUnknownIsNotNonRegulated:
    """비규제(LTV 70%)가 가장 느슨하므로 모르는 것을 그쪽으로 뭉개면 안 된다."""

    def test_malformed_code_is_unresolved(self) -> None:
        resolved = resolve_region(as_of=_TODAY, region_code="서울")
        assert resolved.zone is None
        assert not resolved.is_resolved

    def test_no_input_is_unresolved(self) -> None:
        assert resolve_region(as_of=_TODAY).zone is None

    def test_a_name_that_is_not_designated_cannot_be_called_non_regulated(self) -> None:
        # 이름만 주면 오타인지 비규제인지 구분할 수 없다 — 코드가 있어야 확정된다.
        resolved = resolve_region(as_of=_TODAY, region_name="없는구")
        assert resolved.zone is None

    def test_a_stale_list_refuses_to_call_anything_non_regulated(self) -> None:
        # 목록 확인 시점 이후 기준일이면 새 고시가 있었을 수 있다.
        future = date(DESIGNATION_LIST_VERIFIED_THROUGH.year + 1, 1, 1)
        resolved = resolve_region(as_of=future, region_code="30200")
        assert resolved.zone is None
        assert resolved.note is not None
        assert "단정하지 않습니다" in resolved.note

        # 반면 지정된 지역은 목록이 낡아도 규제지역인 것이 뒤집히지 않는다.
        still_regulated = resolve_region(as_of=future, region_code="11680")
        assert still_regulated.zone is RegulationZone.SPECULATION_OVERHEATED


class TestNonRegulatedIsConfirmedWhenTheListIsCurrent:
    def test_a_local_code_is_non_regulated(self) -> None:
        resolved = resolve_region(as_of=_TODAY, region_code="30200")  # 대전 유성구
        assert resolved.zone is RegulationZone.NON_REGULATED
        assert resolved.is_capital_region is False

    def test_incheon_is_capital_but_not_regulated(self) -> None:
        # 수도권 여부와 규제지역 여부는 별개 축이다.
        resolved = resolve_region(as_of=_TODAY, region_code="28110")
        assert resolved.zone is RegulationZone.NON_REGULATED
        assert resolved.is_capital_region is True


class TestCapitalRegionPrefix:
    def test_seoul_gyeonggi_incheon_are_capital(self) -> None:
        assert is_capital_region_code("11680") is True
        assert is_capital_region_code("41135") is True
        assert is_capital_region_code("28110") is True

    def test_others_are_not(self) -> None:
        assert is_capital_region_code("30200") is False
        assert is_capital_region_code("26110") is False

    def test_malformed_is_none(self) -> None:
        assert is_capital_region_code("ab") is None
        assert is_capital_region_code("") is None


class TestCodesWeCouldNotVerify:
    """코드를 확인하지 못한 지역은 조용히 사라지지 않고 목록으로 드러나야 한다."""

    def test_only_dongtan_is_missing_a_code(self) -> None:
        # 화성시는 2026-02-01 분구로 동탄구가 신설돼 행정구역코드를 확인하지 못했다.
        assert [row.name for row in DESIGNATIONS_WITHOUT_CODE] == ["화성시 동탄구"]

    def test_it_still_resolves_by_name(self) -> None:
        resolved = resolve_region(as_of=_TODAY, region_name="화성시 동탄구")
        assert resolved.zone is RegulationZone.SPECULATION_OVERHEATED

    def test_every_other_designation_has_a_five_digit_code(self) -> None:
        for row in REGION_DESIGNATIONS:
            if row in DESIGNATIONS_WITHOUT_CODE:
                continue
            assert row.code is not None
            assert len(row.code) == 5 and row.code.isdigit(), row.name


class TestNonexistentCodesAreRejected:
    """숫자이기만 하면 통과시키면 없는 코드가 비규제(가장 느슨)로 판정된다."""

    def test_unknown_sido_prefix_is_unresolved(self) -> None:
        resolved = resolve_region(as_of=_TODAY, region_code="99999")
        assert resolved.zone is None, "존재하지 않는 시·도 코드가 비규제로 판정되면 안 된다"

    def test_wrong_length_is_unresolved(self) -> None:
        assert resolve_region(as_of=_TODAY, region_code="1168").zone is None
        assert resolve_region(as_of=_TODAY, region_code="116800").zone is None

    def test_real_sido_prefixes_are_accepted(self) -> None:
        assert is_valid_region_code("11680") is True   # 서울
        assert is_valid_region_code("48170") is True   # 경남
        assert is_valid_region_code("51110") is True   # 강원특별자치도
        assert is_valid_region_code("99999") is False
