from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

# `baseList.loan_lmt` 자유텍스트를 사람이 검수해 구조화한 상품 한도표다.
#
# 왜 정규식 파서(normalizers/loan_product.parse_max_loan_amount)로는 부족한가:
# 원문 9건 중 8건의 한도가 **단일 숫자가 아니라 차주 속성에 따른 분기**다.
#
#   "최대 3.5억원 이내 (재직기간 1년미만 시 최대 1억원 이내,
#    종합통장자동대출은 최대 1.5억원 이내)"
#
# 파서는 이런 문장에서 하나의 숫자를 고를 수 없으므로 None(모름)을 반환하고,
# 그 결과 어댑터가 `product_limit_amount` 결측으로 계산을 포기해 왔다. 문제는
# "파싱 실패"가 아니라 **표현력 부족**이다 — 한도는 스칼라가 아니라 조건부 표다.
#
# 같은 분기 로직이 이미 Rule Pack에 있다는 점이 이 모듈의 설계 근거다. 예컨대
# `packs/kb_credit_loan.py`의 `_loan_amount_within_tier()`는 위 문장을 그대로
# 인코딩하지만 **"요청액이 한도 이내인가"(bool)** 만 답한다. 계산 엔진이 필요한
# 것은 **"한도가 얼마인가"(금액)** 이다. 이 모듈은 그 짝이며, Rule Pack과 동일한
# facts 어휘(`is_overdraft_type`, `owned_house_count`, `lease_deposit` 등)를 쓴다.
# 두 곳의 숫자가 어긋나면 안 되므로 tests에서 교차 검증한다.
#
# 결측 처리 규약 — Rule Pack의 "추측 금지"를 금액 맥락으로 옮기면 UNKNOWN이
# 아니라 **보수적 하한**이 된다. 조건을 몰라 한도가 [1억, 3.5억] 사이임만 아는
# 경우, 1억을 쓰면 대출가능액을 과소평가할 뿐 과대평가하지 않는다. 어느 쪽으로
# 틀렸는지 사용자가 알 수 있도록 가정한 내용을 `assumptions`에 남긴다.
# 다만 비율 한도(임차보증금의 80% 등)의 기준값이 없으면 상한 자체가 빠져
# **과대평가**가 되므로 이때는 UNKNOWN으로 돌린다.


class LimitKind(StrEnum):
    """상품 한도 해석 결과의 3진 값.

    `UNCAPPED`가 `UNKNOWN`과 별도인 것이 이 모듈의 핵심이다. 원문
    "담보조사가격 및 소득금액 ... 에 따른 대출가능금액 이내"는 한도를 모른다는
    뜻이 아니라 **상품 고유의 상한이 없고 LTV·DTI·DSR 계산이 곧 한도**라는
    뜻이다. 둘을 뭉개면 정상 주택담보대출이 영구히 계산 불가로 남는다.
    """

    AMOUNT = "AMOUNT"
    UNCAPPED = "UNCAPPED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ResolvedProductLimit:
    """차주 facts를 반영해 확정한 상품 한도."""

    kind: LimitKind
    amount: Decimal | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    missing_facts: tuple[str, ...] = field(default_factory=tuple)
    note: str | None = None
    # 상품 최소 실행금액. 상한이 아니라 하한이며, 계산된 대출가능액이 이보다
    # 작으면 그 상품은 실행할 수 없다. 상한과 함께 실어 보내는 이유는 이 값이
    # 계산 **이후** 판정에 필요한데 그 시점에는 한도표에 접근할 수 없기 때문이다.
    minimum_amount: Decimal | None = None

    @property
    def is_conservative(self) -> bool:
        """조건을 확인하지 못해 더 낮은 한도를 가정했는지 여부."""
        return bool(self.assumptions)


@dataclass(frozen=True)
class LimitRule:
    """기본 한도를 대체하는 조건부 한도 한 줄.

    `applies`는 Rule Pack의 predicate와 같은 3진 반환이다 — True(적용),
    False(미적용), None(판단할 값이 없음).
    """

    amount: Decimal
    description: str
    applies: Callable[[Mapping[str, object]], bool | None]
    required_facts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProductLoanLimit:
    """상품 1건의 한도 구조.

    `default_amount`가 None이면 상품 자체 상한이 없다는 뜻이다(UNCAPPED).
    `min_amount`는 최소 대출금액이며 상한이 아니다 — 계산된 대출가능액이 이보다
    작으면 그 상품은 실행 불가라는 판단에 쓰라고 함께 싣는다.
    """

    product_name: str
    source_text: str
    default_amount: Decimal | None
    default_description: str
    rules: tuple[LimitRule, ...] = field(default_factory=tuple)
    min_amount: Decimal | None = None
    deposit_ratio: Decimal | None = None
    deposit_ratio_fact: str | None = None
    review_note: str | None = None

    def resolve(self, facts: Mapping[str, object]) -> ResolvedProductLimit:
        """차주 facts로 이 상품의 한도를 확정한다.

        규칙은 선언 순서대로 평가하며 먼저 True가 된 규칙이 이긴다. 따라서
        더 낮은(엄격한) 조건을 앞에 선언한다.

        **앞선 규칙이 None이면 뒤의 True도 확정이 아니다.** 판단하지 못한 규칙이
        실제로는 참일 수 있고, 그렇다면 그쪽이 먼저 적용돼 더 낮은 한도가 된다.
        그래서 True를 만나도 그 금액을 확정으로 쓰지 않고 남은 가능성에 합쳐
        최저값을 고른다 — 과소평가는 안전하지만 과대평가는 아니다.
        """
        # 아직 배제하지 못한 (한도, 근거). 판단 못 한 규칙이 여기 쌓인다.
        candidates: list[tuple[Decimal, str]] = []
        missing: list[str] = []
        certain: tuple[Decimal, str] | None = None

        for rule in self.rules:
            verdict = rule.applies(facts)
            if verdict is True:
                certain = (rule.amount, rule.description)
                break
            if verdict is None:
                candidates.append((rule.amount, rule.description))
                missing.extend(name for name in rule.required_facts if facts.get(name) is None)

        # True인 규칙이 없으면 기본 한도가 남은 가능성이다. default_amount가
        # None(UNCAPPED)이면 유한한 가능성이 아니므로 후보에 넣지 않는다.
        if certain is not None:
            fallback: tuple[Decimal, str] | None = certain
        elif self.default_amount is not None:
            fallback = (self.default_amount, self.default_description)
        else:
            fallback = None

        assumptions: list[str] = []
        base: Decimal | None
        if not candidates:
            base, decided_description = fallback if fallback is not None else (
                None,
                self.default_description,
            )
        else:
            pool = candidates if fallback is None else [*candidates, fallback]
            base, decided_description = min(pool, key=lambda item: item[0])
            unresolved = ", ".join(sorted(set(missing))) or "일부 조건"
            assumptions.append(
                f"{unresolved} 미확인 → "
                f"가능한 한도 중 최저({_format_won(base)}) 적용 "
                f"[{'; '.join(description for _, description in pool)}]"
            )

        if self.deposit_ratio is not None:
            ratio_result = self._apply_deposit_ratio(facts, base)
            if ratio_result.kind is LimitKind.UNKNOWN:
                return ratio_result
            base = ratio_result.amount

        if base is None:
            return ResolvedProductLimit(
                kind=LimitKind.UNCAPPED,
                assumptions=tuple(assumptions),
                note=decided_description,
                minimum_amount=self.min_amount,
            )
        return ResolvedProductLimit(
            kind=LimitKind.AMOUNT,
            amount=base,
            assumptions=tuple(assumptions),
            note=decided_description,
            minimum_amount=self.min_amount,
        )

    def _apply_deposit_ratio(
        self,
        facts: Mapping[str, object],
        base: Decimal | None,
    ) -> ResolvedProductLimit:
        """임차보증금 대비 비율 한도를 겹쳐 적용한다.

        정액 한도와 달리 이 상한은 **빠뜨리면 과대평가**가 되므로 기준값이 없으면
        보수적 하한으로 넘어가지 않고 UNKNOWN을 반환한다.
        """
        assert self.deposit_ratio is not None
        assert self.deposit_ratio_fact is not None

        deposit = facts.get(self.deposit_ratio_fact)
        if deposit is None:
            return ResolvedProductLimit(
                kind=LimitKind.UNKNOWN,
                missing_facts=(self.deposit_ratio_fact,),
                note=(
                    f"{self.deposit_ratio_fact}이(가) 없어 "
                    f"'{self.deposit_ratio_fact}의 "
                    f"{self.deposit_ratio * 100:.0f}%' 한도를 적용할 수 없습니다."
                ),
            )
        ratio_cap = Decimal(str(deposit)) * self.deposit_ratio
        return ResolvedProductLimit(
            kind=LimitKind.AMOUNT,
            amount=ratio_cap if base is None else min(base, ratio_cap),
        )


def _format_won(amount: Decimal) -> str:
    return f"{amount:,.0f}원"


# --- facts 조건 --------------------------------------------------------------
# 모두 Rule Pack이 이미 쓰는 키다. 새 키를 만들지 않는 것이 중요하다 — 판정과
# 한도가 서로 다른 어휘를 쓰면 같은 차주에 대해 앞뒤가 안 맞는 결과가 나온다.


def _flag(name: str) -> Callable[[Mapping[str, object]], bool | None]:
    def check(facts: Mapping[str, object]) -> bool | None:
        value = facts.get(name)
        if value is None:
            return None
        return bool(value)

    return check


def _owns_house(facts: Mapping[str, object]) -> bool | None:
    count = facts.get("owned_house_count")
    if count is None:
        return None
    return int(count) >= 1  # type: ignore[arg-type]


def _owns_house_in_regulated_region(facts: Mapping[str, object]) -> bool | None:
    owns = _owns_house(facts)
    regulated = facts.get("is_regulated_region")
    if owns is None or regulated is None:
        return None
    return owns and bool(regulated)


def _employed_under_one_year(facts: Mapping[str, object]) -> bool | None:
    months = facts.get("employment_months")
    if months is None:
        return None
    return int(months) < 12  # type: ignore[arg-type]


# --- 상품별 한도표 ------------------------------------------------------------
# `source_text`는 selected_23_products.json / DB `loan_product_details.loan_lmt_raw`
# 원문 그대로다. 원문이 바뀌면 테스트가 깨지도록 함께 싣는다.

KB_MORTGAGE_LOAN_LIMIT = ProductLoanLimit(
    product_name="KB 주택담보대출",
    source_text=(
        "담보조사가격 및 소득금액, 담보물건지 지역 등에 따른 대출가능금액 이내 "
        "(통장자동대출 최고 3억원 이내)"
    ),
    default_amount=None,
    default_description="상품 고유 상한 없음 — 담보조사가격·소득금액에 따른 LTV·DTI 계산이 곧 한도",
    rules=(
        LimitRule(
            amount=Decimal("300000000"),
            description="통장자동대출 최고 3억원",
            applies=_flag("is_overdraft_type"),
            required_facts=("is_overdraft_type",),
        ),
    ),
    review_note=(
        "본문에 정액 상한이 없다는 판단이 이 표의 유일한 해석 쟁점이다. "
        "'담보조사가격 및 소득금액 등에 따른 대출가능금액'은 LTV·DTI·DSR 계산 "
        "결과 그 자체이므로 별도 상품 한도로 중복 반영하지 않는다."
    ),
)

HF_BOGEUMJARI_LOAN_LIMIT = ProductLoanLimit(
    product_name="한국주택금융공사 아낌e-보금자리론",
    source_text="3.6억원 이내 (다자녀가구/전세사기피해자 4억원, 생애최초 주택구입자 4.2억원 이내)",
    default_amount=Decimal("360000000"),
    default_description="기본 3.6억원",
    rules=(
        LimitRule(
            amount=Decimal("420000000"),
            description="생애최초 주택구입자 4.2억원",
            applies=_flag("is_first_home_buyer"),
            required_facts=("is_first_home_buyer",),
        ),
        LimitRule(
            amount=Decimal("400000000"),
            description="다자녀가구/전세사기피해자 4억원",
            applies=_flag("is_multi_child_or_jeonse_fraud_victim"),
            required_facts=("is_multi_child_or_jeonse_fraud_victim",),
        ),
    ),
)

KB_STAR_APARTMENT_MORTGAGE_LOAN_LIMIT = ProductLoanLimit(
    product_name="KB스타 아파트담보대출(주택자금)",
    source_text=(
        "담보평가 및 소득금액 등에 따른 대출가능금액 이내 (최소 1천만원 이상 최대 10억원 이내)"
    ),
    default_amount=Decimal("1000000000"),
    default_description="최대 10억원",
    min_amount=Decimal("10000000"),
)

KB_STAR_JEONSE_LOAN_HUG_LIMIT = ProductLoanLimit(
    product_name="KB스타 전세자금대출(HUG_주택도시보증공사)",
    source_text=(
        "최소 5백만원 이상 최대 4억원 (1주택 보유자는 최대 2억원) 이하 "
        "(임차보증금액의 80% 이내 등)"
    ),
    default_amount=Decimal("400000000"),
    default_description="무주택 최대 4억원",
    rules=(
        LimitRule(
            amount=Decimal("200000000"),
            description="1주택 보유자 최대 2억원",
            applies=_owns_house,
            required_facts=("owned_house_count",),
        ),
    ),
    min_amount=Decimal("5000000"),
    deposit_ratio=Decimal("0.80"),
    deposit_ratio_fact="lease_deposit",
)

KB_STAR_JEONSE_LOAN_HF_LIMIT = ProductLoanLimit(
    product_name="KB스타 전세자금대출(HF_한국주택금융공사)",
    source_text=(
        "최소 5백만원 이상 최대 2억 2천 2백만원 이내 "
        "(신혼부부 또는 다둥이가구의 경우 최대 2억원 이내)"
    ),
    default_amount=Decimal("222000000"),
    default_description="기본 2억 2천 2백만원",
    rules=(
        LimitRule(
            amount=Decimal("200000000"),
            description="신혼부부/다둥이가구 최대 2억원",
            applies=_flag("is_newlywed_or_multi_child"),
            required_facts=("is_newlywed_or_multi_child",),
        ),
    ),
    min_amount=Decimal("5000000"),
    review_note=(
        "우대 대상(신혼부부·다둥이가구)의 한도가 오히려 낮은 구조다. 원문과 "
        "packs/kb_star_jeonse_loan_hf.py가 동일하게 그렇게 적혀 있어 그대로 "
        "옮겼으나, 상품설명서 대조로 한 번 확인할 값이다."
    ),
)

KB_STAR_JEONSE_LOAN_SGI_LIMIT = ProductLoanLimit(
    product_name="KB스타 전세자금대출(SGI_서울보증보험)",
    source_text=(
        "최소 5백만원 이상 최대 5억원 이하 "
        "(임차보증금액의 80% 이내, 1주택자 최대 3억원 이내, 규제지역 1주택자 2억원 제한)"
    ),
    default_amount=Decimal("500000000"),
    default_description="무주택 최대 5억원",
    rules=(
        LimitRule(
            amount=Decimal("200000000"),
            description="규제지역 1주택자 2억원",
            applies=_owns_house_in_regulated_region,
            required_facts=("owned_house_count", "is_regulated_region"),
        ),
        LimitRule(
            amount=Decimal("300000000"),
            description="1주택자 최대 3억원",
            applies=_owns_house,
            required_facts=("owned_house_count",),
        ),
    ),
    min_amount=Decimal("5000000"),
    deposit_ratio=Decimal("0.80"),
    deposit_ratio_fact="lease_deposit",
)

KB_CREDIT_LOAN_LIMIT = ProductLoanLimit(
    product_name="KB 신용대출",
    source_text=(
        "최대 3.5억원 이내 "
        "(재직기간 1년미만 시 최대 1억원 이내, 종합통장자동대출은 최대 1.5억원 이내)"
    ),
    default_amount=Decimal("350000000"),
    default_description="기본 최대 3.5억원",
    rules=(
        LimitRule(
            amount=Decimal("100000000"),
            description="재직기간 1년 미만 최대 1억원",
            applies=_employed_under_one_year,
            required_facts=("employment_months",),
        ),
        LimitRule(
            amount=Decimal("150000000"),
            description="종합통장자동대출 최대 1.5억원",
            applies=_flag("is_overdraft_type"),
            required_facts=("is_overdraft_type",),
        ),
    ),
)

KB_SALARY_CREDIT_LOAN_LIMIT = ProductLoanLimit(
    product_name="KB 급여이체신용대출",
    source_text="무보증 최고 1억5천만원 이내 (종합통장자동대출 최고 1억원 이내)",
    default_amount=Decimal("150000000"),
    default_description="무보증 최고 1억 5천만원",
    rules=(
        LimitRule(
            amount=Decimal("100000000"),
            description="종합통장자동대출 최고 1억원",
            applies=_flag("is_overdraft_type"),
            required_facts=("is_overdraft_type",),
        ),
    ),
)

KB_EMERGENCY_CASH_LOAN_LIMIT = ProductLoanLimit(
    product_name="KB 비상금대출",
    source_text="최소 50만원 ~ 최대 300만원",
    default_amount=Decimal("3000000"),
    default_description="최대 300만원",
    min_amount=Decimal("500000"),
)

PRODUCT_LOAN_LIMITS: tuple[ProductLoanLimit, ...] = (
    KB_MORTGAGE_LOAN_LIMIT,
    HF_BOGEUMJARI_LOAN_LIMIT,
    KB_STAR_APARTMENT_MORTGAGE_LOAN_LIMIT,
    KB_STAR_JEONSE_LOAN_HUG_LIMIT,
    KB_STAR_JEONSE_LOAN_HF_LIMIT,
    KB_STAR_JEONSE_LOAN_SGI_LIMIT,
    KB_CREDIT_LOAN_LIMIT,
    KB_SALARY_CREDIT_LOAN_LIMIT,
    KB_EMERGENCY_CASH_LOAN_LIMIT,
)

_BY_PRODUCT_NAME: dict[str, ProductLoanLimit] = {
    limit.product_name: limit for limit in PRODUCT_LOAN_LIMITS
}


def get_product_loan_limit(product_name: str) -> ProductLoanLimit | None:
    """상품명으로 한도표를 찾는다. 검수되지 않은 상품이면 None이다."""
    return _BY_PRODUCT_NAME.get(product_name.strip())


def resolve_product_limit(
    product_name: str,
    facts: Mapping[str, object],
) -> ResolvedProductLimit:
    """상품명 + 차주 facts로 한도를 확정한다.

    표에 없는 상품은 UNKNOWN이다 — 검수되지 않은 상품에 임의 한도를 부여하는
    것이 이 모듈이 막으려는 사고 그 자체이기 때문이다.
    """
    limit = get_product_loan_limit(product_name)
    if limit is None:
        return ResolvedProductLimit(
            kind=LimitKind.UNKNOWN,
            note=f"{product_name!r}은 검수된 상품 한도표에 없습니다.",
        )
    return limit.resolve(facts)
