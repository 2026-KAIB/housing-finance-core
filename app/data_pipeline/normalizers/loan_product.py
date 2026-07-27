import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

# 부록 B-5의 원천 대출 상품 스키마(baseList/optionList, source_type="manual_pdf")를
# 계산 엔진이 쓸 수 있는 단위·타입으로 바꾼다. CLAUDE.md 규약대로 Rule Engine·계산
# 엔진은 원천 스키마를 직접 소비하지 않으며, 확정할 수 없는 값은 임의 숫자로
# 대체하지 않고 None으로 남긴다(부록 B-5).
#
# 이 모듈이 실제로 막아주는 두 가지 사고:
#   1. optionList의 lend_rate_*는 "퍼센트 숫자"(5.2 = 연 5.2%)인데 formulas.py의
#      annual_rate는 "비율"(0.052)을 요구한다. 그대로 넘기면 상환액이 100배가 된다.
#   2. baseList.loan_lmt은 자유텍스트라 조건부 한도가 여러 개 섞여 있다. 무조건
#      첫 숫자를 뽑으면 엉뚱한 한도를 상품 한도로 쓰게 된다.

_AMOUNT_UNIT_MULTIPLIERS = {
    "억": 100_000_000,
    "천만": 10_000_000,
    "백만": 1_000_000,
    "만": 10_000,
}

_AMOUNT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:억|천만|백만|만)?\s*원")
_MAX_AMOUNT_RE = re.compile(r"(?:최대|최고)\s*(\d+(?:\.\d+)?)\s*(억|천만|백만|만)?\s*원")
_PARENTHESES_RE = re.compile(r"\([^)]*\)")


@dataclass(frozen=True)
class NormalizedLoanOption:
    """optionList 한 행 = 담보유형·상환방식·금리유형 조합 하나의 금리 구간.

    `annual_rate_*`는 모두 **비율**이다 (연 5.2% → `Decimal("0.052")`).
    """

    product_name: str
    mortgage_type_name: str | None
    repayment_type_name: str | None
    rate_type_name: str | None
    annual_rate_min: Decimal
    annual_rate_max: Decimal
    annual_rate_avg: Decimal

    def rate(self, selection: str = "avg") -> Decimal:
        """금리 구간 중 하나를 고른다. 어떤 값을 쓸지는 호출자의 정책이다."""
        if selection == "min":
            return self.annual_rate_min
        if selection == "max":
            return self.annual_rate_max
        if selection == "avg":
            return self.annual_rate_avg
        raise ValueError(f"알 수 없는 금리 선택 기준입니다: {selection!r} (min/avg/max)")


@dataclass(frozen=True)
class NormalizedLoanProduct:
    """상품 1건 = baseList 1개 + optionList N개를 정규화한 결과."""

    product_name: str
    # 상품별 대출한도(§13.1-3). 자유텍스트에서 명확히 읽히지 않으면 None이며,
    # 이 경우 호출자는 상품 한도를 "모름"으로 취급해야 한다(임의값 금지).
    max_loan_amount: Decimal | None
    options: tuple[NormalizedLoanOption, ...] = field(default_factory=tuple)


def _percent_to_ratio(value: object) -> Decimal:
    return Decimal(str(value)) / Decimal(100)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_max_loan_amount(loan_lmt: object) -> Decimal | None:
    """`baseList.loan_lmt` 자유텍스트에서 상품 최대 한도를 읽는다.

    **조건부 한도가 섞여 있으면 파싱하지 않고 None을 반환한다.** 원천 데이터의
    한도 문구는 아래처럼 형태가 제각각이라 "최대"라는 단어만 보고 숫자를 뽑으면
    잘못된 한도를 쓰게 된다(부록 B-5, CLAUDE.md "하지 말 것"):

    - `"최소 1천만원 이상 최대 10억원 이내"` → 10억 (단일 한도, 파싱 가능)
    - `"최대 3.5억원 이내 (재직기간 1년미만 시 최대 1억원 이내, ...)"` → None
      (괄호 안에 조건부 한도가 더 있음)
    - `"담보조사가격 ... 대출가능금액 이내 (통장자동대출 최고 3억원 이내)"` → None
      (본문 한도가 담보조사가격 의존이라 숫자로 확정 불가)

    괄호 안에 금액 표현이 하나라도 있으면 조건부 한도로 보고 포기한다. 남은
    본문에 `최대`/`최고` 금액 표현이 정확히 하나일 때만 그 값을 반환한다.
    """
    text = _optional_str(loan_lmt)
    if text is None:
        return None

    for parenthesized in _PARENTHESES_RE.findall(text):
        if _AMOUNT_RE.search(parenthesized):
            return None

    outer_text = _PARENTHESES_RE.sub(" ", text)
    matches = _MAX_AMOUNT_RE.findall(outer_text)
    if len(matches) != 1:
        return None

    number, unit = matches[0]
    multiplier = _AMOUNT_UNIT_MULTIPLIERS.get(unit, 1)
    return Decimal(number) * Decimal(multiplier)


def normalize_loan_options(
    option_list: Sequence[Mapping[str, object]],
) -> tuple[NormalizedLoanOption, ...]:
    """optionList를 정규화한다. 금리 3종이 모두 있는 행만 사용한다.

    `lend_rate_min`/`lend_rate_max`/`lend_rate_avg` 중 하나라도 없으면 그 행은
    금리를 확정할 수 없으므로 건너뛴다(0으로 채우지 않는다).
    """
    normalized: list[NormalizedLoanOption] = []
    for option in option_list:
        rate_min = option.get("lend_rate_min")
        rate_max = option.get("lend_rate_max")
        rate_avg = option.get("lend_rate_avg")
        if rate_min is None or rate_max is None or rate_avg is None:
            continue
        normalized.append(
            NormalizedLoanOption(
                product_name=str(option.get("fin_prdt_nm", "")),
                mortgage_type_name=_optional_str(option.get("mrtg_type_nm")),
                repayment_type_name=_optional_str(option.get("rpay_type_nm")),
                rate_type_name=_optional_str(option.get("lend_rate_type_nm")),
                annual_rate_min=_percent_to_ratio(rate_min),
                annual_rate_max=_percent_to_ratio(rate_max),
                annual_rate_avg=_percent_to_ratio(rate_avg),
            )
        )
    return tuple(normalized)


def normalize_loan_product(
    base_data: Mapping[str, object],
    option_list: Sequence[Mapping[str, object]],
) -> NormalizedLoanProduct:
    """부록 B-5 원천 대출 상품 1건을 정규화 모델로 변환한다."""
    return NormalizedLoanProduct(
        product_name=str(base_data.get("fin_prdt_nm", "")),
        max_loan_amount=parse_max_loan_amount(base_data.get("loan_lmt")),
        options=normalize_loan_options(option_list),
    )
