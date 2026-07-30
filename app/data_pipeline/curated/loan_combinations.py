"""대출 상품을 **동시에** 실행할 수 있는지에 대한 사람 검수표.

왜 이 모듈이 필요한가:
    조합 추천("주담대 3억 + 신용대출 1억")은 두 대출이 같은 차주에게 동시에
    실행될 수 있다는 전제 위에 서 있다. 그런데 그 전제는 **원천 데이터에 없다.**
    `selected_23_products.json`과 DB `loan_product_details`의 대출 9건 전문을
    검색해도 중복 이용 조항이 한 건도 없다(2026-07-30 확인). 부록 B-5의 필드
    목록에도 해당 항목이 없다.

    확인하지 못한 채 조합하면 **존재할 수 없는 대안에 점수까지 붙여** 추천한다.
    이 저장소가 반복해서 고쳐 온 실패 유형("모르는 것을 느슨한 쪽으로 뭉개기")
    이므로, 미확인 조합은 허용하지 않고 `UNKNOWN`으로 남긴다.

무엇을 판단하지 않는가:
    이 표는 **동시 실행 가능성**만 다룬다. 자금용도 배타성(전세자금대출로 주택을
    매수할 수 없다)은 조합 문제가 아니라 목표 유형 문제이므로 상위 계층의
    `goal_type`·`for_house_purchase`가 이미 걸러낸다. 여기서 다시 판정하지 않는다.

판정 3진값:
    `ALLOWED`/`BLOCKED`/`UNKNOWN`. 규제표(`regulations/*.py`)와 같이 출처를 함께
    들고 다니며, `verified=False`인 줄은 기본 조회에서 제외한다.

쌍 단위인 이유:
    조합은 3개까지 가능하지만 근거는 항상 두 상품 사이의 관계로 진술된다("선순위
    저당권이 있으면 취급 불가"). 그래서 쌍으로 검수하고, 부분집합은 **모든 쌍이
    ALLOWED일 때만** 실행 가능으로 본다. 한 쌍이라도 UNKNOWN이면 그 조합 전체가
    미확인이다 — 나머지 쌍이 확인됐다는 사실이 모르는 쌍을 덮지 않는다.

1차 출처
  [HF-보금] 한국주택금융공사 「보금자리론 업무처리기준」 제9장 2. 1순위
            한정근저당권의 설정 (2026-07-30 확인)
            https://www.hf.go.kr/ko/sub01/sub01_01_01.do
            "양수대상 자산선정기준일 기준 본건 저당권보다 우선하는 제한물권
            없을 것. 다만, 아래 항목은 본건 저당권보다 우선 가능
             (1) 전세권 또는 공공 목적으로 행정관청 등 공공기관이 설정한
                 지상권ㆍ지역권의 경우
             (2) 선순위 저당권이 주택도시기금대출, 공사 보금자리론,
                 나라사랑대출인 경우 ..."
            → 허용 예외 목록에 **은행 일반 주택담보대출이 없다.** 따라서 담보
              주택에 은행 주담대가 선순위로 설정돼 있으면 보금자리론을 취급할
              수 없다.
            같은 문서 제11장 4.: 생애최초 주택구입자금 대출은 "전세권, 공사
            보금자리론은 선순위 제한물권으로 인정하지 않음" — 더 엄격하다.
            같은 문서 제15장 8.: "다중채무자는 담보주택에 주택담보대출이 2건
            이상 존재하는 채무자를 의미" — 주담대 2건 병존 자체는 현실에서
            발생함을 규정이 전제한다. 즉 아래 BLOCKED는 "물리적으로 불가"가
            아니라 "이 상품의 취급요건 위반"이다.

  [FSC-DSR] 금융위원회 「주택담보대출이 생활안정자금 목적인 경우 등 자주 하는
            질문」·차주단위 DSR 안내 (2026-07-30 확인)
            https://www.fsc.go.kr/po020201/27351
            "주택담보대출 잔액이 있는 상태에서 차주가 여타 대출을 받는 경우에
            차주 단위 DSR을 산출" — 주담대와 신용대출의 병행 보유를 규제가
            전제하고, 한도는 금지가 아니라 **DSR 합산**으로 관리한다.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

# 검수 기준일. 이 날짜 이후로 약관이 바뀌었을 수 있으므로, 조합 추천을 운영에
# 쓰기 전에 재확인한다. 규제지역 지정 목록과 같은 규율이다.
COMBINATION_TABLE_VERIFIED_AT = "2026-07-30"


class CombinationVerdict(StrEnum):
    """두 상품을 동시에 실행할 수 있는가.

    `UNKNOWN`이 `BLOCKED`와 별도인 것이 이 표의 핵심이다. "확인 결과 불가"와
    "확인하지 못함"은 사용자에게 다르게 보여야 한다 — 전자는 사유를 제시할 수
    있고 후자는 무엇을 확인해야 하는지 제시해야 한다.
    """

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CombinationRule:
    """상품 두 건의 동시 실행 가능성 한 줄.

    `products`는 순서 없는 쌍이다. 조회할 때 정렬해 맞추므로 선언 순서는
    가독성만의 문제다.
    """

    products: tuple[str, str]
    verdict: CombinationVerdict
    source: str
    note: str
    verified: bool = True
    # 이 판정이 특정 차주 조건에서만 성립하면 그 조건을 적는다. 조회자는 해당
    # facts를 확인하지 못하면 판정을 확정으로 쓰지 않는다.
    required_facts: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        first, second = self.products
        if not first.strip() or not second.strip():
            raise ValueError("상품명은 비어 있을 수 없습니다.")
        if first == second:
            raise ValueError(f"같은 상품끼리의 조합은 표에 넣지 않습니다: {first}")
        if not self.source.strip():
            raise ValueError("판정에는 출처가 필요합니다.")
        if not self.note.strip():
            raise ValueError("판정에는 근거 설명이 필요합니다.")

    @property
    def key(self) -> tuple[str, str]:
        return _pair_key(*self.products)


def _pair_key(first: str, second: str) -> tuple[str, str]:
    a, b = first.strip(), second.strip()
    return (a, b) if a <= b else (b, a)


# --- 상품명 상수 --------------------------------------------------------------
# 한도표(`loan_limits.py`)와 **같은 문자열**을 쓴다. 두 표가 다른 이름을 쓰면
# 한쪽이 조회에 실패하면서 조용히 결측으로 빠진다.

KB_MORTGAGE = "KB 주택담보대출"
HF_BOGEUMJARI = "한국주택금융공사 아낌e-보금자리론"
KB_STAR_APARTMENT = "KB스타 아파트담보대출(주택자금)"
KB_CREDIT = "KB 신용대출"
KB_PAYROLL_CREDIT = "KB 급여이체신용대출"
KB_EMERGENCY_CREDIT = "KB 비상금대출"

MORTGAGE_PRODUCTS = (KB_MORTGAGE, HF_BOGEUMJARI, KB_STAR_APARTMENT)
CREDIT_PRODUCTS = (KB_CREDIT, KB_PAYROLL_CREDIT, KB_EMERGENCY_CREDIT)

_BOGEUMJARI_NOTE = (
    "보금자리론은 1순위 한정근저당권 설정이 취급요건이고, 선순위로 허용되는 "
    "저당권은 주택도시기금대출·공사 보금자리론·나라사랑대출뿐이다. 은행 일반 "
    "주택담보대출은 허용 목록에 없으므로 같은 주택을 담보로 동시 실행할 수 없다. "
    "생애최초 주택구입자금 대출은 전세권과 보금자리론까지 선순위로 인정하지 "
    "않아 더 엄격하다(제11장 4)."
)

_CROSS_COLLATERAL_NOTE = (
    "주택담보대출과 신용대출은 담보가 달라 근저당권 순위 요건이 서로 걸리지 "
    "않는다. 규제는 병행 보유를 금지하지 않고 차주단위 DSR 합산으로 관리하므로, "
    "조합 엔진이 DSR·현금흐름 예산을 **공유 예산으로 함께 차감**해야 한다. "
    "개별 한도를 각각 계산해 더하면 그 예산을 두 번 쓴다."
)

_SAME_BANK_MORTGAGE_NOTE = (
    "같은 은행의 주택담보대출 2건을 한 담보주택에 동시 실행할 수 있는지는 "
    "공개 약관·상품설명서에서 확인하지 못했다. 은행 내규(담보 순위, 한도 통합 "
    "관리) 사안이라 영업점 확인이 필요하다. 규정상 주담대 2건 병존 자체는 "
    "가능하지만(HF 업무처리기준 제15장 8의 다중채무자 정의), 그 사실이 이 두 "
    "상품의 동시 취급 가능성을 뜻하지는 않는다."
)

_CREDIT_STACK_NOTE = (
    "동일 은행 신용대출 2건의 동시 실행 가능 여부와 한도 통합 관리 방식을 "
    "공개 자료에서 확인하지 못했다. 신용대출은 잔액 1억원 초과 시 스트레스 "
    "가산금리 대상이 되므로(`regulations/stress_dsr.py`), 합산 잔액이 그 문턱을 "
    "넘는지가 조합의 DSR에 직접 영향을 준다 — 추측으로 열어 둘 수 없다."
)


def _blocked_with_bogeumjari(other: str) -> CombinationRule:
    return CombinationRule(
        products=(HF_BOGEUMJARI, other),
        verdict=CombinationVerdict.BLOCKED,
        source="[HF-보금] 보금자리론 업무처리기준 제9장 2",
        note=_BOGEUMJARI_NOTE,
    )


def _allowed_cross_collateral(mortgage: str, credit: str) -> CombinationRule:
    return CombinationRule(
        products=(mortgage, credit),
        verdict=CombinationVerdict.ALLOWED,
        source="[FSC-DSR] 금융위원회 차주단위 DSR 안내",
        note=_CROSS_COLLATERAL_NOTE,
    )


def _unknown(first: str, second: str, note: str) -> CombinationRule:
    return CombinationRule(
        products=(first, second),
        verdict=CombinationVerdict.UNKNOWN,
        source="확인된 출처 없음",
        note=note,
        verified=False,
    )


COMBINATION_RULES: tuple[CombinationRule, ...] = (
    # 확인 결과 불가 — 근저당권 순위 요건 위반.
    _blocked_with_bogeumjari(KB_MORTGAGE),
    _blocked_with_bogeumjari(KB_STAR_APARTMENT),
    # 확인 결과 가능 — 담보가 다르고 규제가 DSR 합산으로 관리한다.
    *(
        _allowed_cross_collateral(mortgage, credit)
        for mortgage in MORTGAGE_PRODUCTS
        for credit in CREDIT_PRODUCTS
    ),
    # 미확인 — 은행 내규 사안.
    _unknown(KB_MORTGAGE, KB_STAR_APARTMENT, _SAME_BANK_MORTGAGE_NOTE),
    _unknown(KB_CREDIT, KB_PAYROLL_CREDIT, _CREDIT_STACK_NOTE),
    _unknown(KB_CREDIT, KB_EMERGENCY_CREDIT, _CREDIT_STACK_NOTE),
    _unknown(KB_PAYROLL_CREDIT, KB_EMERGENCY_CREDIT, _CREDIT_STACK_NOTE),
)

_BY_PAIR: dict[tuple[str, str], CombinationRule] = {
    rule.key: rule for rule in COMBINATION_RULES
}
if len(_BY_PAIR) != len(COMBINATION_RULES):
    raise RuntimeError("조합 검수표에 같은 쌍이 두 번 선언되었습니다.")


@dataclass(frozen=True)
class ResolvedCombination:
    """부분집합 하나에 대한 동시 실행 가능성 판정."""

    verdict: CombinationVerdict
    # BLOCKED·UNKNOWN을 만든 쌍과 사유. 사용자 화면에 "왜 이 조합이 빠졌는가"로
    # 그대로 실린다.
    blocking_pairs: tuple[tuple[tuple[str, str], str], ...] = field(
        default_factory=tuple
    )
    unknown_pairs: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_executable(self) -> bool:
        return self.verdict is CombinationVerdict.ALLOWED


def get_combination_rule(
    first: str,
    second: str,
    *,
    allow_unverified: bool = False,
) -> CombinationRule | None:
    """쌍 하나의 검수 결과. 표에 없으면 ``None``(=미확인).

    미검증 줄을 쓰려면 ``allow_unverified=True``를 명시해야 한다 — 규제표와 같은
    규율이다. 기본 조회에서 제외되므로 호출자가 실수로 UNKNOWN을 통과로
    읽을 수 없다.
    """
    rule = _BY_PAIR.get(_pair_key(first, second))
    if rule is None:
        return None
    if not rule.verified and not allow_unverified:
        return None
    return rule


def resolve_combination(
    product_names: Sequence[str],
    *,
    allow_unverified: bool = False,
) -> ResolvedCombination:
    """부분집합 전체가 동시에 실행 가능한지 판정한다.

    **모든 쌍이 ALLOWED일 때만** 실행 가능이다. 한 쌍이 BLOCKED면 조합이 불가고,
    BLOCKED가 없더라도 UNKNOWN 쌍이 하나라도 있으면 확정할 수 없다. 확인된 쌍이
    많다는 사실이 모르는 쌍을 덮지 않는다.

    상품이 1건이면 조합이 아니므로 항상 ALLOWED다.
    """
    unique = tuple(dict.fromkeys(name.strip() for name in product_names))
    if len(unique) <= 1:
        return ResolvedCombination(verdict=CombinationVerdict.ALLOWED)

    blocking: list[tuple[tuple[str, str], str]] = []
    unknown: list[tuple[str, str]] = []
    sources: list[str] = []

    for index, first in enumerate(unique):
        for second in unique[index + 1 :]:
            pair = _pair_key(first, second)
            rule = _BY_PAIR.get(pair)
            if rule is None:
                unknown.append(pair)
                continue
            if not rule.verified and not allow_unverified:
                unknown.append(pair)
                continue
            if rule.verdict is CombinationVerdict.BLOCKED:
                blocking.append((pair, rule.note))
                sources.append(rule.source)
            elif rule.verdict is CombinationVerdict.UNKNOWN:
                unknown.append(pair)
            else:
                sources.append(rule.source)

    if blocking:
        verdict = CombinationVerdict.BLOCKED
    elif unknown:
        verdict = CombinationVerdict.UNKNOWN
    else:
        verdict = CombinationVerdict.ALLOWED

    return ResolvedCombination(
        verdict=verdict,
        blocking_pairs=tuple(blocking),
        unknown_pairs=tuple(dict.fromkeys(unknown)),
        sources=tuple(dict.fromkeys(sources)),
    )


def unverified_pairs() -> tuple[tuple[str, str], ...]:
    """아직 출처로 확정하지 못한 쌍. 검수 대기 목록으로 쓴다."""
    return tuple(rule.key for rule in COMBINATION_RULES if not rule.verified)


def describe_missing_verification() -> tuple[str, ...]:
    """미확인 쌍마다 무엇을 확인해야 하는지. 보고서에 그대로 싣는다."""
    return tuple(
        f"{first} + {second}: {rule.note}"
        for rule in COMBINATION_RULES
        if not rule.verified
        for first, second in (rule.key,)
    )


def known_product_names() -> tuple[str, ...]:
    """검수표가 다루는 상품명. 한도표와의 이름 일치를 테스트가 확인한다."""
    names: set[str] = set()
    for rule in COMBINATION_RULES:
        names.update(rule.products)
    return tuple(sorted(names))


def _iter_pairs(names: Iterable[str]) -> Iterable[tuple[str, str]]:
    ordered = tuple(dict.fromkeys(names))
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            yield _pair_key(first, second)


def coverage_report(product_names: Sequence[str]) -> Mapping[str, tuple[str, ...]]:
    """주어진 상품 목록에서 검수표가 덮는 쌍과 비는 쌍을 보고한다."""
    covered: list[str] = []
    missing: list[str] = []
    for first, second in _iter_pairs(product_names):
        rule = _BY_PAIR.get((first, second))
        label = f"{first} + {second}"
        if rule is not None and rule.verified:
            covered.append(label)
        else:
            missing.append(label)
    return {"covered": tuple(covered), "missing": tuple(missing)}


__all__ = [
    "COMBINATION_RULES",
    "COMBINATION_TABLE_VERIFIED_AT",
    "CombinationRule",
    "CombinationVerdict",
    "CREDIT_PRODUCTS",
    "MORTGAGE_PRODUCTS",
    "ResolvedCombination",
    "coverage_report",
    "describe_missing_verification",
    "get_combination_rule",
    "known_product_names",
    "resolve_combination",
    "unverified_pairs",
]
