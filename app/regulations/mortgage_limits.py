from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.engines.loan.formulas import principal_from_pmt

# 주택담보대출의 **법정** 상한표다(§9.1, 부록 A-2의 `ltv_limit_amount`·
# `dti_limit_amount` 공급원). 상품별 한도(data_pipeline/curated/loan_limits.py)와
# 달리 여기 값은 은행이 정하는 것이 아니라 정부 규제이며, 대책 발표마다 바뀐다.
#
# 그래서 이 모듈의 모든 상수는 **출처와 시행일을 함께** 들고 다닌다. 기준일을
# 넘겨 조회하게 만든 이유도 같다 — 규제는 소급되지 않으므로 "언제 기준의 한도인가"가
# 답의 일부다. 출처를 확인하지 못한 값은 `verified=False`로 표시하고 기본적으로
# 반환하지 않는다(§20: 검증되지 않은 규제 상수 사용 금지).
#
# 1차 출처
#   [6·27]  금융위원회 「수도권 중심의 가계부채 관리 강화 방안」 2025-06-27
#           (LTV 0% 금지 구간, 생애최초 80%→70%, 처분조건부 1주택 규제지역 50%,
#            주택구입목적 주담대 최대한도 6억원)
#   [10·15] 「주택시장 안정화를 위한 대출수요 관리 방안」 2025-10-15,
#           시행 2025-10-16 (서울 전역·경기 12곳 투기과열지구 지정,
#           주택가격 구간별 한도 6억/4억/2억, 스트레스 금리 하한 1.5%→3.0%)
#   [26·6·30] 금융위원회 「규제지역 추가 지정 관련 긴급 가계부채 점검회의」
#           2026-06-30, 시행 2026-07-01 (화성 동탄구·용인 기흥구·구리시 추가,
#           "규제지역 내 주담대 취급시 LTV 강화(비규제지역 70% → 규제지역 40%)")
#   DTI 산식·비율은 SSOT §13.2.2 / 부록 A-14 참조(은행업감독업무시행세칙).


class RegulationZone(StrEnum):
    """규제지역 구분. 같은 시·군·구가 두 지정을 동시에 받을 수 있으며, 그때는
    더 강한 투기과열지구 기준을 쓴다."""

    SPECULATION_OVERHEATED = "SPECULATION_OVERHEATED"  # 투기과열지구
    ADJUSTMENT_TARGET = "ADJUSTMENT_TARGET"  # 조정대상지역
    NON_REGULATED = "NON_REGULATED"  # 비규제지역


class HousingStatus(StrEnum):
    """LTV 비율을 가르는 차주 구분(6·27 방안)."""

    NO_HOUSE = "NO_HOUSE"  # 무주택
    FIRST_HOME_BUYER = "FIRST_HOME_BUYER"  # 생애최초 주택구입
    ONE_HOUSE_DISPOSAL_PLEDGED = "ONE_HOUSE_DISPOSAL_PLEDGED"  # 1주택 처분조건부
    ONE_HOUSE_KEEPING = "ONE_HOUSE_KEEPING"  # 1주택 미처분 추가구입
    MULTI_HOUSE = "MULTI_HOUSE"  # 2주택 이상


@dataclass(frozen=True)
class RegulatoryRatio:
    """출처가 붙은 규제 비율 하나."""

    ratio: Decimal
    source: str
    effective_from: date
    verified: bool = True
    note: str | None = None


@dataclass(frozen=True)
class ResolvedPolicyLimit:
    """규제 한도 산출 결과. 확정하지 못하면 `amount`는 None이다."""

    amount: Decimal | None
    binding_reason: str | None = None
    sources: tuple[str, ...] = field(default_factory=tuple)
    missing_inputs: tuple[str, ...] = field(default_factory=tuple)
    note: str | None = None


_SIX_TWENTY_SEVEN = "금융위 「수도권 중심의 가계부채 관리 강화 방안」(2025-06-27)"
_TEN_FIFTEEN = "「주택시장 안정화를 위한 대출수요 관리 방안」(2025-10-15, 시행 2025-10-16)"
_JUNE_2026 = (
    "금융위 「규제지역 추가 지정 관련 긴급 가계부채 점검회의」(2026-06-30, 시행 2026-07-01)"
)

# (구역, 차주구분) → LTV 비율.
LTV_RATIOS: dict[tuple[RegulationZone, HousingStatus], RegulatoryRatio] = {
    # 추가 주택구입 목적 대출 금지. 지역·차주 무관하게 0%다.
    (RegulationZone.SPECULATION_OVERHEATED, HousingStatus.MULTI_HOUSE): RegulatoryRatio(
        ratio=Decimal("0"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="2주택 이상 보유자의 수도권·규제지역 추가 주택구입 목적 주담대 금지",
    ),
    (RegulationZone.ADJUSTMENT_TARGET, HousingStatus.MULTI_HOUSE): RegulatoryRatio(
        ratio=Decimal("0"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="2주택 이상 보유자의 수도권·규제지역 추가 주택구입 목적 주담대 금지",
    ),
    (RegulationZone.SPECULATION_OVERHEATED, HousingStatus.ONE_HOUSE_KEEPING): RegulatoryRatio(
        ratio=Decimal("0"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="1주택자가 기존 주택을 처분하지 않고 추가 구입하는 경우 금지",
    ),
    (RegulationZone.ADJUSTMENT_TARGET, HousingStatus.ONE_HOUSE_KEEPING): RegulatoryRatio(
        ratio=Decimal("0"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="1주택자가 기존 주택을 처분하지 않고 추가 구입하는 경우 금지",
    ),
    # 무주택·처분조건부 1주택.
    (RegulationZone.SPECULATION_OVERHEATED, HousingStatus.NO_HOUSE): RegulatoryRatio(
        ratio=Decimal("0.40"),
        source=_JUNE_2026,
        effective_from=date(2026, 7, 1),
        note="원문 '비규제지역 70% → 규제지역 40%'",
    ),
    (RegulationZone.SPECULATION_OVERHEATED, HousingStatus.ONE_HOUSE_DISPOSAL_PLEDGED): (
        RegulatoryRatio(
            ratio=Decimal("0.40"),
            source=_JUNE_2026,
            effective_from=date(2026, 7, 1),
            note="처분조건부 1주택자는 무주택자와 동일 취급(6·27)",
        )
    ),
    (RegulationZone.NON_REGULATED, HousingStatus.NO_HOUSE): RegulatoryRatio(
        ratio=Decimal("0.70"),
        source=_JUNE_2026,
        effective_from=date(2025, 6, 28),
        note="비규제지역 70%",
    ),
    (RegulationZone.NON_REGULATED, HousingStatus.ONE_HOUSE_DISPOSAL_PLEDGED): RegulatoryRatio(
        ratio=Decimal("0.70"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="처분조건부 1주택자 비규제지역 70%",
    ),
    # 생애최초.
    (RegulationZone.SPECULATION_OVERHEATED, HousingStatus.FIRST_HOME_BUYER): RegulatoryRatio(
        ratio=Decimal("0.70"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="수도권·규제지역 생애최초 80% → 70%, 6개월 이내 전입의무",
    ),
    (RegulationZone.NON_REGULATED, HousingStatus.FIRST_HOME_BUYER): RegulatoryRatio(
        ratio=Decimal("0.80"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        verified=False,
        note=(
            "6·27은 '수도권·규제지역' 생애최초만 70%로 낮췄다. 비규제지역이 종전 "
            "80%로 남는다는 것은 반대해석이며 원문에 명시되어 있지 않다. "
            "1차 출처 확인 전까지 사용 금지."
        ),
    ),
    # 조정대상지역 단독 지정(투기과열 미지정) 구간.
    (RegulationZone.ADJUSTMENT_TARGET, HousingStatus.NO_HOUSE): RegulatoryRatio(
        ratio=Decimal("0.50"),
        source="(미확인)",
        effective_from=date(2025, 6, 28),
        verified=False,
        note=(
            "6·27의 '처분조건부 1주택자 규제지역 50%' 문구에서 조정대상지역 50%를 "
            "유추한 값이다. 2026-06-30 보도자료는 규제지역을 40%로만 언급하며 "
            "투기과열/조정대상을 구분하지 않는다. 두 지정을 함께 받은 지역은 "
            "SPECULATION_OVERHEATED로 조회할 것."
        ),
    ),
    (RegulationZone.ADJUSTMENT_TARGET, HousingStatus.ONE_HOUSE_DISPOSAL_PLEDGED): RegulatoryRatio(
        ratio=Decimal("0.50"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        verified=False,
        note="위와 동일한 사유로 미검증.",
    ),
    (RegulationZone.ADJUSTMENT_TARGET, HousingStatus.FIRST_HOME_BUYER): RegulatoryRatio(
        ratio=Decimal("0.70"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        note="수도권·규제지역 생애최초 70%",
    ),
    (RegulationZone.NON_REGULATED, HousingStatus.ONE_HOUSE_KEEPING): RegulatoryRatio(
        ratio=Decimal("0.70"),
        source=_SIX_TWENTY_SEVEN,
        effective_from=date(2025, 6, 28),
        verified=False,
        note="6·27의 추가구입 금지는 수도권·규제지역 한정이다. 비규제지역 취급 미확인.",
    ),
    (RegulationZone.NON_REGULATED, HousingStatus.MULTI_HOUSE): RegulatoryRatio(
        ratio=Decimal("0.60"),
        source="(미확인)",
        effective_from=date(2025, 6, 28),
        verified=False,
        note="비규제지역 다주택자 LTV 미확인. 사용 금지.",
    ),
}

# 수도권·규제지역 **주택구입 목적** 주담대의 주택가격 구간별 절대 한도(10·15).
# LTV 비율 계산과 별개로 겹쳐 적용되는 상한이다.
MORTGAGE_HARD_CAP_TIERS: tuple[tuple[Decimal | None, Decimal], ...] = (
    (Decimal("1500000000"), Decimal("600000000")),
    (Decimal("2500000000"), Decimal("400000000")),
    (None, Decimal("200000000")),
)
MORTGAGE_HARD_CAP_EFFECTIVE_FROM = date(2025, 10, 16)

# DTI 비율(SSOT §13.2.2 / 부록 A-14). 은행이 아니라 감독규정이 정한다.
DTI_RATIOS: dict[str, RegulatoryRatio] = {
    "SEOUL": RegulatoryRatio(
        ratio=Decimal("0.50"),
        source="은행업감독업무시행세칙 (SSOT §13.2.2 / A-14)",
        effective_from=date(2018, 10, 31),
        note="서울 50%",
    ),
    "CAPITAL_REGION": RegulatoryRatio(
        ratio=Decimal("0.60"),
        source="은행업감독업무시행세칙 (SSOT §13.2.2 / A-14)",
        effective_from=date(2018, 10, 31),
        note="수도권(서울 외) 60%",
    ),
}

# 1금융권 차주단위 DSR 상한. `safe_dsr`(서비스 내부 안전기준)과 혼동 금지.
BANK_DSR_LIMIT = RegulatoryRatio(
    ratio=Decimal("0.40"),
    source="금융위 차주단위 DSR 규제(1금융권)",
    effective_from=date(2022, 7, 1),
)


def get_ltv_ratio(
    zone: RegulationZone,
    status: HousingStatus,
    *,
    as_of: date,
    allow_unverified: bool = False,
) -> RegulatoryRatio | None:
    """(구역, 차주구분) 조합의 LTV 비율을 찾는다.

    표에 없거나, 기준일이 시행일보다 이르거나, 미검증 값이면 None이다.
    미검증 값을 굳이 쓰려면 `allow_unverified=True`를 명시해야 한다 — 규제 상수를
    말없이 추측하는 것이 이 저장소가 금지하는 사고이므로 호출부에 흔적을 남긴다.
    """
    ratio = LTV_RATIOS.get((zone, status))
    if ratio is None:
        return None
    if as_of < ratio.effective_from:
        return None
    if not ratio.verified and not allow_unverified:
        return None
    return ratio


def get_mortgage_hard_cap(house_price: Decimal, *, as_of: date) -> Decimal | None:
    """수도권·규제지역 주택구입 목적 주담대의 주택가격 구간별 절대 한도(10·15)."""
    if as_of < MORTGAGE_HARD_CAP_EFFECTIVE_FROM:
        return None
    for upper_bound, cap in MORTGAGE_HARD_CAP_TIERS:
        if upper_bound is None or house_price <= upper_bound:
            return cap
    return None


def resolve_ltv_limit_amount(
    *,
    house_price: Decimal,
    zone: RegulationZone,
    status: HousingStatus,
    is_capital_region: bool,
    as_of: date,
    for_house_purchase: bool = True,
    allow_unverified: bool = False,
) -> ResolvedPolicyLimit:
    """LTV 비율과 절대 한도를 모두 적용한 대출 상한 금액.

    두 규제는 별개이며 **둘 다** 걸린다 — 예컨대 20억원 주택을 비규제지역에서
    사면 LTV 70%로 14억이지만, 수도권·규제지역이라면 4억이 별도로 씌워진다.
    """
    if house_price <= 0:
        raise ValueError("house_price는 0보다 커야 합니다.")

    ratio = get_ltv_ratio(zone, status, as_of=as_of, allow_unverified=allow_unverified)
    if ratio is None:
        return ResolvedPolicyLimit(
            amount=None,
            missing_inputs=("ltv_ratio",),
            note=(
                f"{zone}/{status} 조합의 LTV 비율을 확정할 수 없습니다 "
                f"(미등재이거나 {as_of} 기준 미시행, 또는 출처 미확인)."
            ),
        )

    amount = house_price * ratio.ratio
    binding = f"LTV {ratio.ratio * 100:.0f}%"
    sources = [ratio.source]

    regulated = zone is not RegulationZone.NON_REGULATED
    if for_house_purchase and (is_capital_region or regulated):
        hard_cap = get_mortgage_hard_cap(house_price, as_of=as_of)
        if hard_cap is not None and hard_cap < amount:
            amount = hard_cap
            binding = f"주택가격 구간별 한도 {hard_cap:,.0f}원"
            sources.append(_TEN_FIFTEEN)

    return ResolvedPolicyLimit(
        amount=amount,
        binding_reason=binding,
        sources=tuple(sources),
        note=ratio.note,
    )


def resolve_dti_limit_amount(
    *,
    annual_income: Decimal,
    dti_ratio: Decimal,
    other_annual_interest: Decimal,
    annual_rate: Decimal,
    months: int,
) -> ResolvedPolicyLimit:
    """DTI 상한을 만족하는 신규 주담대 최대 원금(§13.2.2 / 부록 A-14).

    DTI = (신규 주담대 연 원리금 + 기타 부채 연 이자) ÷ 연소득 이므로,
    신규 대출에 허용되는 연 원리금은 `연소득 × DTI − 기타부채 연 이자`이고
    거기서 원금을 역산한다.

    기타 부채 이자만으로 이미 상한을 채운 경우 한도는 0원이다 — 이때는 "모름"이
    아니라 실제로 0이므로 UNKNOWN으로 돌리지 않는다.
    """
    if annual_income <= 0:
        raise ValueError("annual_income은 0보다 커야 합니다.")

    allowed_annual = annual_income * dti_ratio - other_annual_interest
    if allowed_annual <= 0:
        return ResolvedPolicyLimit(
            amount=Decimal("0"),
            binding_reason=f"기존 부채 연 이자만으로 DTI {dti_ratio * 100:.0f}% 소진",
        )

    principal = principal_from_pmt(allowed_annual / Decimal(12), annual_rate, months)
    return ResolvedPolicyLimit(
        amount=principal,
        binding_reason=f"DTI {dti_ratio * 100:.0f}%",
    )
