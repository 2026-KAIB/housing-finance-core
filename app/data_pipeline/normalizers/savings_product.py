from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.engines.savings.models import InterestType, SavingsProductKind


@dataclass(frozen=True)
class NormalizedSavingsOption:
    """예적금 계산기가 이해하는 단위로 정규화된 공시 옵션."""

    product_name: str
    term_months: int
    interest_type: InterestType
    annual_base_rate: Decimal
    annual_max_rate: Decimal
    reserve_type: str | None = None
    reserve_type_name: str | None = None
    interest_type_name: str | None = None


@dataclass(frozen=True)
class SavingsOptionNormalizationIssue:
    """임의의 기본값으로 대체하지 않고 상위 계층에 돌려보낼 옵션 오류."""

    option_index: int
    missing_or_invalid_fields: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class NormalizedSavingsProduct:
    """상품 설명 원문과 계산 가능한 금리 옵션을 함께 보존한다."""

    product_name: str
    product_kind: SavingsProductKind
    maturity_interest: str | None
    max_limit: Decimal | None
    rate_beyond_contract_max: str | None
    extra_rate_info: object | None
    options: tuple[NormalizedSavingsOption, ...]
    issues: tuple[SavingsOptionNormalizationIssue, ...] = field(default_factory=tuple)


_INTEREST_TYPE_CODES = {
    "S": InterestType.SIMPLE,
    "M": InterestType.COMPOUND,
}


class _OptionNormalizationError(ValueError):
    def __init__(self, fields: tuple[str, ...], reason: str) -> None:
        super().__init__(reason)
        self.fields = fields


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}은(는) 숫자여야 합니다.")
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name}은(는) 숫자여야 합니다.") from error
    if not converted.is_finite():
        raise ValueError(f"{field_name}은(는) 유한한 숫자여야 합니다.")
    return converted


def _positive_months(value: object) -> int:
    converted = _decimal(value, "save_trm")
    if converted != converted.to_integral_value() or converted <= 0:
        raise ValueError("save_trm은(는) 0보다 큰 정수여야 합니다.")
    return int(converted)


def _percent_to_ratio(value: object, field_name: str) -> Decimal:
    percent = _decimal(value, field_name)
    if percent < 0:
        raise ValueError(f"{field_name}은(는) 음수일 수 없습니다.")
    return percent / Decimal(100)


def _optional_limit(value: object) -> Decimal | None:
    if value is None:
        return None
    limit = _decimal(value, "max_limit")
    if limit < 0:
        raise ValueError("max_limit은(는) 음수일 수 없습니다.")
    return limit


def _normalize_option(
    option: Mapping[str, object],
    *,
    product_name: str,
    product_kind: SavingsProductKind,
) -> NormalizedSavingsOption:
    required = ("save_trm", "intr_rate_type", "intr_rate", "intr_rate2")
    missing = tuple(field_name for field_name in required if option.get(field_name) is None)
    if product_kind is SavingsProductKind.INSTALLMENT_SAVINGS:
        if option.get("rsrv_type") is None:
            missing += ("rsrv_type",)
        if option.get("rsrv_type_nm") is None:
            missing += ("rsrv_type_nm",)
    if missing:
        raise _OptionNormalizationError(
            missing,
            f"필수 필드가 없습니다: {', '.join(missing)}",
        )

    interest_code = str(option["intr_rate_type"]).strip().upper()
    try:
        interest_type = _INTEREST_TYPE_CODES[interest_code]
    except KeyError as error:
        raise _OptionNormalizationError(
            ("intr_rate_type",),
            f"지원하지 않는 intr_rate_type입니다: {interest_code!r}",
        ) from error

    try:
        term_months = _positive_months(option["save_trm"])
    except ValueError as error:
        raise _OptionNormalizationError(("save_trm",), str(error)) from error
    try:
        annual_base_rate = _percent_to_ratio(option["intr_rate"], "intr_rate")
    except ValueError as error:
        raise _OptionNormalizationError(("intr_rate",), str(error)) from error
    try:
        annual_max_rate = _percent_to_ratio(option["intr_rate2"], "intr_rate2")
    except ValueError as error:
        raise _OptionNormalizationError(("intr_rate2",), str(error)) from error
    if annual_max_rate < annual_base_rate:
        raise _OptionNormalizationError(
            ("intr_rate", "intr_rate2"),
            "intr_rate2는 intr_rate보다 작을 수 없습니다.",
        )

    return NormalizedSavingsOption(
        product_name=str(option.get("fin_prdt_nm") or product_name),
        term_months=term_months,
        interest_type=interest_type,
        annual_base_rate=annual_base_rate,
        annual_max_rate=annual_max_rate,
        reserve_type=_optional_str(option.get("rsrv_type")),
        reserve_type_name=_optional_str(option.get("rsrv_type_nm")),
        interest_type_name=_optional_str(option.get("intr_rate_type_nm")),
    )


def normalize_savings_product(
    base_data: Mapping[str, object],
    option_list: Sequence[Mapping[str, object]],
    *,
    product_kind: SavingsProductKind,
) -> NormalizedSavingsProduct:
    """저축형 원천 데이터를 계산 가능한 옵션과 명시적 오류로 분리한다.

    원천의 금리는 퍼센트 숫자이고 계산기는 비율을 받는다. 해석 불가능한 옵션은
    0원·0%로 채우거나 조용히 제거하지 않고 ``issues``에 남긴다.
    """

    product_name = str(base_data.get("fin_prdt_nm", "")).strip()
    options: list[NormalizedSavingsOption] = []
    issues: list[SavingsOptionNormalizationIssue] = []

    for index, raw_option in enumerate(option_list):
        try:
            options.append(
                _normalize_option(
                    raw_option,
                    product_name=product_name,
                    product_kind=product_kind,
                )
            )
        except _OptionNormalizationError as error:
            issues.append(
                SavingsOptionNormalizationIssue(
                    option_index=index,
                    missing_or_invalid_fields=error.fields,
                    reason=str(error),
                )
            )

    return NormalizedSavingsProduct(
        product_name=product_name,
        product_kind=product_kind,
        maturity_interest=_optional_str(base_data.get("mtrt_int")),
        max_limit=_optional_limit(base_data.get("max_limit")),
        rate_beyond_contract_max=_optional_str(
            base_data.get("rate_beyond_contract_max")
        ),
        extra_rate_info=base_data.get("extra_rate_info"),
        options=tuple(options),
        issues=tuple(issues),
    )
