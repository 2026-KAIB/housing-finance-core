from dataclasses import dataclass
from datetime import date

from app.regulations.mortgage_limits import RegulationZone

# 규제지역(투기과열지구·조정대상지역) 지정 목록이다. `RegulationZone`을 정하는
# 유일한 근거이며, 이 표가 없으면 LTV·스트레스 금리를 아예 조회할 수 없다.
#
# **"목록에 없음"과 "비규제"를 구분하는 것이 이 모듈의 핵심이다.** 비규제지역이
# 가장 느슨하기 때문이다(LTV 70% vs 규제지역 40%). 지정 목록은 전수 목록이므로
# 목록에 없으면 비규제가 맞지만, 그것은 **목록이 최신일 때만** 참이다. 새 지정을
# 아직 반영하지 못한 상태에서 "목록에 없으니 비규제"라고 답하면 규제지역 주택을
# 70%로 계산해 한도를 크게 과대평가한다.
#
# 그래서 목록에 유효기한(`DESIGNATION_LIST_VERIFIED_THROUGH`)을 달았다. 그 이후
# 기준일로 조회하면서 목록에 없는 지역은 비규제로 단정하지 않고 확정 실패를
# 돌려준다. 새 고시를 반영할 때마다 이 날짜를 함께 올린다.
#
# 지정은 해제되기도 하므로 시행구간(`effective_from`~`effective_to`)을 갖는다.
# `mortgage_limits.LTV_RATIO_HISTORY`와 같은 구조다.
#
# 한 지역이 투기과열지구와 조정대상지역으로 **동시에** 지정될 수 있고, 그때는
# 더 강한 투기과열지구 기준을 쓴다(`RegulationZone` docstring). 2026-07-28 현재
# 지정된 모든 지역이 두 지정을 함께 받았으므로 조정대상지역 **단독** 지정 목록은
# 비어 있다.
#
# 1차 출처
#   [10·15] 「주택시장 안정화 대책」(2025-10-15, 지정 효력 2025-10-16)
#           서울 25개 자치구 전역 + 경기 12곳을 투기과열지구·조정대상지역 지정.
#           (기존 지정 4개구: 강남·서초·송파·용산 유지 + 21개구 신규)
#           https://www.korea.kr/news/policyNewsView.do?newsId=148950973
#   [26·7·1] 화성시 동탄구·용인시 기흥구·구리시 투기과열지구·조정대상지역 추가
#           지정, "7월 1일부터 지정효력이 발생한다".
#           https://www.korea.kr/news/policyNewsView.do?newsId=148967354
#   지정 현황 원표: 국토교통부 「조정대상지역 및 투기과열지구 지정 현황」
#           https://www.molit.go.kr/policy/stable/sta_b_03.jsp


@dataclass(frozen=True)
class RegionDesignation:
    """시·군·구 하나의 규제지역 지정 이력 한 줄."""

    sido: str
    name: str
    zone: RegulationZone
    effective_from: date
    effective_to: date | None = None
    # 행정구역코드(법정동 시군구 5자리). 확인하지 못한 지역은 None이며 이름으로만
    # 매칭된다 — 코드를 추측해 넣으면 엉뚱한 지역이 규제지역으로 판정된다.
    code: str | None = None
    source: str = ""

    def covers(self, as_of: date) -> bool:
        if as_of < self.effective_from:
            return False
        return self.effective_to is None or as_of <= self.effective_to


@dataclass(frozen=True)
class ResolvedRegion:
    """지역 조회 결과. `zone`이 None이면 확정하지 못한 것이다."""

    zone: RegulationZone | None
    is_capital_region: bool | None = None
    name: str | None = None
    sources: tuple[str, ...] = ()
    note: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.zone is not None and self.is_capital_region is not None


_TEN_FIFTEEN = "「주택시장 안정화 대책」(2025-10-15, 지정효력 2025-10-16)"
_JULY_2026 = "경기도 규제지역 추가 지정(지정효력 2026-07-01)"

_TEN_FIFTEEN_FROM = date(2025, 10, 16)
_JULY_2026_FROM = date(2026, 7, 1)

# 수도권 시·도 코드 앞 2자리. 규제지역 여부와 **별개 축**이다 — 비규제지역이어도
# 수도권이면 스트레스 가산금리 3.00%p가 붙는다(stress_dsr.py).
CAPITAL_REGION_PREFIXES = ("11", "28", "41")  # 서울, 인천, 경기

# 실재하는 시·도 코드 앞 2자리. 숫자이기만 하면 통과시키면 안 된다 — 없는 코드가
# 비규제(가장 느슨한 구분)로 판정돼 한도가 과대평가된다.
# 42/45는 강원·전북이 특별자치도로 전환되기 전 코드이며 과거 데이터를 위해 남긴다.
SIDO_PREFIXES = frozenset(
    {
        "11",  # 서울특별시
        "26",  # 부산광역시
        "27",  # 대구광역시
        "28",  # 인천광역시
        "29",  # 광주광역시
        "30",  # 대전광역시
        "31",  # 울산광역시
        "36",  # 세종특별자치시
        "41",  # 경기도
        "42",  # (구) 강원도
        "43",  # 충청북도
        "44",  # 충청남도
        "45",  # (구) 전라북도
        "46",  # 전라남도
        "47",  # 경상북도
        "48",  # 경상남도
        "50",  # 제주특별자치도
        "51",  # 강원특별자치도
        "52",  # 전북특별자치도
    }
)

# 이 날짜까지는 지정 목록이 전수임을 확인했다. 이후 기준일로 조회하면 "목록에
# 없음"을 비규제로 단정하지 않는다 — 그 사이 새 고시가 있었을 수 있기 때문이다.
# 국토교통부 「조정대상지역 및 투기과열지구 지정 현황」을 확인하고 함께 올릴 것.
DESIGNATION_LIST_VERIFIED_THROUGH = date(2026, 7, 28)

_SEOUL_DISTRICTS: tuple[tuple[str, str], ...] = (
    ("11110", "종로구"),
    ("11140", "중구"),
    ("11170", "용산구"),
    ("11200", "성동구"),
    ("11215", "광진구"),
    ("11230", "동대문구"),
    ("11260", "중랑구"),
    ("11290", "성북구"),
    ("11305", "강북구"),
    ("11320", "도봉구"),
    ("11350", "노원구"),
    ("11380", "은평구"),
    ("11410", "서대문구"),
    ("11440", "마포구"),
    ("11470", "양천구"),
    ("11500", "강서구"),
    ("11530", "구로구"),
    ("11545", "금천구"),
    ("11560", "영등포구"),
    ("11590", "동작구"),
    ("11620", "관악구"),
    ("11650", "서초구"),
    ("11680", "강남구"),
    ("11710", "송파구"),
    ("11740", "강동구"),
)

# 경기 12곳(10·15). 성남·수원은 구 단위로 지정됐다.
_GYEONGGI_TEN_FIFTEEN: tuple[tuple[str | None, str], ...] = (
    ("41290", "과천시"),
    ("41210", "광명시"),
    ("41135", "성남시 분당구"),
    ("41131", "성남시 수정구"),
    ("41133", "성남시 중원구"),
    ("41117", "수원시 영통구"),
    ("41111", "수원시 장안구"),
    ("41115", "수원시 팔달구"),
    ("41173", "안양시 동안구"),
    ("41465", "용인시 수지구"),
    ("41430", "의왕시"),
    ("41450", "하남시"),
)

# 2026-07-01 추가 3곳. 화성시 동탄구는 2026-02-01 분구로 신설돼 행정구역코드를
# 확인하지 못했다 — 코드를 추측하지 않고 None으로 두어 이름으로만 매칭한다.
_GYEONGGI_JULY_2026: tuple[tuple[str | None, str], ...] = (
    (None, "화성시 동탄구"),
    ("41463", "용인시 기흥구"),
    ("41310", "구리시"),
)


def _build() -> tuple[RegionDesignation, ...]:
    rows: list[RegionDesignation] = []
    for code, name in _SEOUL_DISTRICTS:
        rows.append(
            RegionDesignation(
                sido="서울특별시",
                name=name,
                zone=RegulationZone.SPECULATION_OVERHEATED,
                effective_from=_TEN_FIFTEEN_FROM,
                code=code,
                source=_TEN_FIFTEEN,
            )
        )
    for code, name in _GYEONGGI_TEN_FIFTEEN:
        rows.append(
            RegionDesignation(
                sido="경기도",
                name=name,
                zone=RegulationZone.SPECULATION_OVERHEATED,
                effective_from=_TEN_FIFTEEN_FROM,
                code=code,
                source=_TEN_FIFTEEN,
            )
        )
    for code, name in _GYEONGGI_JULY_2026:
        rows.append(
            RegionDesignation(
                sido="경기도",
                name=name,
                zone=RegulationZone.SPECULATION_OVERHEATED,
                effective_from=_JULY_2026_FROM,
                code=code,
                source=_JULY_2026,
            )
        )
    return tuple(rows)


REGION_DESIGNATIONS: tuple[RegionDesignation, ...] = _build()

# 행정구역코드를 확인하지 못한 지역. 코드로는 조회되지 않으므로 남은 작업으로
# 드러나 있어야 한다(테스트가 이 목록을 고정한다).
DESIGNATIONS_WITHOUT_CODE: tuple[RegionDesignation, ...] = tuple(
    row for row in REGION_DESIGNATIONS if row.code is None
)

_BY_CODE: dict[str, list[RegionDesignation]] = {}
_BY_NAME: dict[str, list[RegionDesignation]] = {}
for _row in REGION_DESIGNATIONS:
    if _row.code is not None:
        _BY_CODE.setdefault(_row.code, []).append(_row)
    _BY_NAME.setdefault(_row.name, []).append(_row)


def is_capital_region_code(region_code: str) -> bool | None:
    """행정구역코드로 수도권 여부를 판정한다. 유효한 시·군·구 코드가 아니면 None."""
    if not is_valid_region_code(region_code):
        return None
    return region_code.strip()[:2] in CAPITAL_REGION_PREFIXES


def is_valid_region_code(region_code: str) -> bool:
    """5자리 숫자이면서 앞 2자리가 실재하는 시·도 코드인지."""
    code = region_code.strip()
    return len(code) == 5 and code.isdigit() and code[:2] in SIDO_PREFIXES


def resolve_region(
    *,
    as_of: date,
    region_code: str | None = None,
    region_name: str | None = None,
) -> ResolvedRegion:
    """지역을 규제지역 구분으로 해석한다.

    코드가 우선이고 이름은 보조다(화성시 동탄구처럼 코드를 확인하지 못한 지역이
    있다). 둘 다 없거나 코드 형식이 아니면 확정하지 못한 것으로 돌려준다.

    지정 목록은 전수 목록이므로 유효한 코드가 목록에 없으면 비규제로 확정한다.
    **단 그것은 목록이 최신일 때만 참이다** — `as_of`가
    `DESIGNATION_LIST_VERIFIED_THROUGH`를 넘으면 비규제로 단정하지 않고 확정
    실패를 돌려준다. 비규제가 가장 느슨한 구분이라(LTV 70%) 낡은 목록으로
    비규제라고 답하면 한도가 과대평가되기 때문이다.
    """
    matches: list[RegionDesignation] = []
    resolved_name = region_name

    if region_code is not None:
        code = region_code.strip()
        capital = is_capital_region_code(code)
        if capital is None:
            return ResolvedRegion(
                zone=None,
                note=(
                    f"유효한 행정구역코드가 아닙니다: {region_code!r} "
                    "(5자리 숫자 + 실재하는 시·도 코드)"
                ),
            )
        matches = [row for row in _BY_CODE.get(code, []) if row.covers(as_of)]
        if matches:
            resolved_name = matches[0].name
        elif region_name is not None:
            # 코드로 못 찾았을 때만 이름으로 보완한다(코드 미확인 지역 구제).
            matches = [row for row in _BY_NAME.get(region_name, []) if row.covers(as_of)]
    elif region_name is not None:
        matches = [row for row in _BY_NAME.get(region_name, []) if row.covers(as_of)]
        capital = True if matches else None
        if not matches:
            return ResolvedRegion(
                zone=None,
                name=region_name,
                note=(
                    f"지역명 {region_name!r}이(가) 지정 목록에 없습니다. "
                    "코드 없이 이름만으로는 비규제 여부를 확정할 수 없습니다."
                ),
            )
    else:
        return ResolvedRegion(zone=None, note="region_code 또는 region_name이 필요합니다.")

    if not matches:
        if as_of > DESIGNATION_LIST_VERIFIED_THROUGH:
            return ResolvedRegion(
                zone=None,
                is_capital_region=capital,
                name=resolved_name,
                note=(
                    f"지정 목록은 {DESIGNATION_LIST_VERIFIED_THROUGH.isoformat()}까지만 "
                    f"확인됐습니다. 기준일 {as_of.isoformat()}에는 새 고시가 있었을 수 "
                    "있어 비규제로 단정하지 않습니다."
                ),
            )
        return ResolvedRegion(
            zone=RegulationZone.NON_REGULATED,
            is_capital_region=capital,
            name=resolved_name,
            sources=(_TEN_FIFTEEN, _JULY_2026),
            note="규제지역 지정 목록에 없어 비규제지역으로 판정",
        )

    # 두 지정을 함께 받았으면 더 강한 투기과열지구를 쓴다.
    zone = (
        RegulationZone.SPECULATION_OVERHEATED
        if any(row.zone is RegulationZone.SPECULATION_OVERHEATED for row in matches)
        else RegulationZone.ADJUSTMENT_TARGET
    )
    return ResolvedRegion(
        zone=zone,
        is_capital_region=capital if capital is not None else True,
        name=resolved_name,
        sources=tuple(dict.fromkeys(row.source for row in matches)),
    )
