from decimal import Decimal

from app.engines.safety import cashflow_buffer

# 이 모듈은 입력 스키마(어댑터/handoff 연결 방식)와 무관하게 확정된 순수 계산
# 공식만 담는다 (DESIGN SSOT §13.3 PMT, §13.2/A-12 DSR, 부록 A-8 Buffer).
# 상품·정책 데이터를 어떻게 받아올지는 아직 팀 논의 중이므로, 이 함수들은
# Decimal 입력만 받고 그 상위 조립(Adapter/계산 엔진 본체)에는 관여하지 않는다.
#
# 단위 계약: annual_rate는 비율(3.5% → Decimal("0.035")), 금액은 원, months는
# 개월이다. 이 계약을 어기는 값(0을 초과하지 않는 기간, 음수 금액 등)은 계산
# 불가능한 입력이므로 ValueError로 즉시 실패한다 — 결측/UNKNOWN 판정으로
# 바꿀지는 이 함수를 호출하는 Adapter/서비스 계층의 책임이다.


def _require_positive(value: Decimal | int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name}은(는) 0보다 커야 합니다.")


def _require_non_negative(value: Decimal, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name}은(는) 음수일 수 없습니다.")


def monthly_rate(annual_rate: Decimal) -> Decimal:
    """대출 월금리는 명목환산(연이율/12)을 쓴다 (§13.3 규약, 예적금 실효환산과 다름)."""
    return annual_rate / Decimal(12)


def pmt(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """원리금균등 월 상환액 (DESIGN SSOT §13.3).

    PMT = L × i(1+i)^n / ((1+i)^n − 1), i = 연이율 ÷ 12
    """
    _require_non_negative(principal, "principal")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(months, "months")

    i = monthly_rate(annual_rate)
    if i == 0:
        return principal / Decimal(months)
    growth = (1 + i) ** months
    return principal * i * growth / (growth - 1)


def principal_from_pmt(monthly_payment: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """월 상환액 상한에서 역산한 원금 = pmt()의 역함수 (§13.3).

    L = PMT × ((1+i)^n − 1) / (i(1+i)^n), i = 연이율 ÷ 12

    DTI·DSR 한도는 "연간 상환액이 소득의 x% 이내"라는 **상환액 제약**이므로,
    이를 금액 한도로 바꾸려면 상환액에서 원금을 되돌려야 한다(§9.1).
    """
    _require_non_negative(monthly_payment, "monthly_payment")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(months, "months")

    i = monthly_rate(annual_rate)
    if i == 0:
        return monthly_payment * Decimal(months)
    growth = (1 + i) ** months
    return monthly_payment * (growth - 1) / (i * growth)


def dsr(
    *,
    existing_annual_debt_service: Decimal,
    new_annual_debt_service: Decimal,
    annual_income: Decimal,
) -> Decimal:
    """DSR = (기존 + 신규) 연간 원리금 상환액 ÷ 연간 소득 (§13.2, 부록 A-12).

    "모든 금융부채"는 기존 대출과 신규(시뮬레이션 대상) 대출을 모두 포함한다.
    """
    _require_non_negative(existing_annual_debt_service, "existing_annual_debt_service")
    _require_non_negative(new_annual_debt_service, "new_annual_debt_service")
    _require_positive(annual_income, "annual_income")

    return (existing_annual_debt_service + new_annual_debt_service) / annual_income


def buffer(monthly_essential_expense: Decimal) -> Decimal:
    """최소 여유자금(Buffer) = max(300,000원, 필수생활비 × 0.10) (부록 A-8)."""
    return cashflow_buffer(monthly_essential_expense)


def loan_max(
    *,
    ltv_limit_amount: Decimal,
    product_limit_amount: Decimal,
    dti_limit_amount: Decimal,
    required_amount: Decimal,
    annual_rate: Decimal,
    months: int,
    existing_annual_debt_service: Decimal,
    annual_income: Decimal,
    safe_dsr: Decimal,
    post_purchase_monthly_income: Decimal,
    post_purchase_monthly_expense: Decimal,
    other_existing_monthly_debt_service: Decimal,
    buffer_target: Decimal,
    dsr_annual_rate: Decimal | None = None,
    epsilon: Decimal = Decimal("100000"),
) -> Decimal:
    """대출 가능액 이분 탐색 (DESIGN SSOT 부록 A-2).

    정책 상한(LTV·상품·DTI 한도)은 이미 금액으로 환산된 값을 인자로 받는다 —
    비율→금액 변환은 이 함수의 책임이 아니다. hi 초기값은 그 한도들과 실제
    필요액 중 최솟값이며, DSR·구매후 현금흐름(Buffer) 조건을 동시에 만족하는
    최대 대출액을 찾을 때까지 이분 탐색한다. L 증가 → pmt·dsr 증가, 월 잉여
    감소로 feasible은 L에 대해 단조이므로 이분 탐색이 유효하다(A-2 원문).

    **금리는 두 곳에 쓰이며 서로 다를 수 있다.** `dsr_annual_rate`를 주면 DSR
    판정에만 그 금리를 쓰고, 월 현금흐름(Buffer) 판정에는 언제나 실제 금리인
    `annual_rate`를 쓴다. 스트레스 DSR이 정확히 이 구조다 — 심사는 가산금리를
    올린 기준으로 하되 차주가 실제로 내는 돈은 실제 금리 기준이기 때문이다
    (`app/regulations/stress_dsr.py`). 주지 않으면 두 판정 모두 실제 금리를 쓰며,
    이는 스트레스 금리를 적용하지 않는다는 뜻이므로 **한도가 과대평가된다.**

    반환값은 항상 실제 가능한 최대 대출액 이하이며(보수적 하향값), 오차는
    epsilon 미만이다 — epsilon 단위로 절사하는 정책은 호출하는 쪽이 정한다.
    """
    _require_positive(epsilon, "epsilon")
    _require_positive(months, "months")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(annual_income, "annual_income")

    assessment_rate = annual_rate if dsr_annual_rate is None else dsr_annual_rate
    _require_non_negative(assessment_rate, "dsr_annual_rate")
    if assessment_rate < annual_rate:
        raise ValueError(
            "dsr_annual_rate는 실제 금리보다 낮을 수 없습니다 "
            f"(annual_rate={annual_rate}, dsr_annual_rate={assessment_rate})."
        )
    for name, value in (
        ("ltv_limit_amount", ltv_limit_amount),
        ("product_limit_amount", product_limit_amount),
        ("dti_limit_amount", dti_limit_amount),
        ("required_amount", required_amount),
        ("existing_annual_debt_service", existing_annual_debt_service),
        ("safe_dsr", safe_dsr),
        ("post_purchase_monthly_income", post_purchase_monthly_income),
        ("post_purchase_monthly_expense", post_purchase_monthly_expense),
        ("other_existing_monthly_debt_service", other_existing_monthly_debt_service),
        ("buffer_target", buffer_target),
    ):
        _require_non_negative(value, name)

    lo = Decimal("0")
    hi = min(ltv_limit_amount, product_limit_amount, dti_limit_amount, required_amount)

    while (hi - lo) > epsilon:
        candidate = (lo + hi) / 2
        # 실제 상환액(현금흐름 판정용)과 심사용 상환액(DSR 판정용)을 나눈다.
        new_pmt = pmt(candidate, annual_rate, months)
        assessed_pmt = (
            new_pmt if assessment_rate == annual_rate else pmt(candidate, assessment_rate, months)
        )
        candidate_dsr = dsr(
            existing_annual_debt_service=existing_annual_debt_service,
            new_annual_debt_service=assessed_pmt * 12,
            annual_income=annual_income,
        )
        monthly_surplus = (
            post_purchase_monthly_income
            - post_purchase_monthly_expense
            - other_existing_monthly_debt_service
            - new_pmt
        )
        feasible = candidate_dsr <= safe_dsr and monthly_surplus >= buffer_target
        if feasible:
            lo = candidate
        else:
            hi = candidate

    return lo


def term_is_serviceable(
    *,
    principal: Decimal,
    annual_rate: Decimal,
    months: int,
    annual_income: Decimal,
    existing_annual_debt_service: Decimal,
    safe_dsr: Decimal,
    post_purchase_monthly_income: Decimal,
    post_purchase_monthly_expense: Decimal,
    other_existing_monthly_debt_service: Decimal,
    buffer_target: Decimal,
    dsr_annual_rate: Decimal | None = None,
) -> bool:
    """이 기간으로 이 금액을 갚을 수 있는가.

    ``loan_max``가 금액을 이분 탐색하며 쓰는 판정과 **글자 그대로 같은 식**이다.
    두 곳이 갈리면 "한도로는 되는데 기간으로는 안 되는" 조합이 나온다.

    DSR은 심사금리로, 월 현금흐름은 실제 금리로 본다. 심사와 실제 부담은 다른
    금리를 쓰기 때문이다(`regulations/stress_dsr.py`).
    """
    _require_positive(months, "months")
    _require_non_negative(principal, "principal")
    _require_non_negative(annual_rate, "annual_rate")
    _require_positive(annual_income, "annual_income")

    assessment_rate = annual_rate if dsr_annual_rate is None else dsr_annual_rate
    if assessment_rate < annual_rate:
        raise ValueError(
            "dsr_annual_rate는 실제 금리보다 낮을 수 없습니다 "
            f"(annual_rate={annual_rate}, dsr_annual_rate={assessment_rate})."
        )

    actual_pmt = pmt(principal, annual_rate, months)
    assessed_pmt = (
        actual_pmt
        if assessment_rate == annual_rate
        else pmt(principal, assessment_rate, months)
    )
    candidate_dsr = dsr(
        existing_annual_debt_service=existing_annual_debt_service,
        new_annual_debt_service=assessed_pmt * 12,
        annual_income=annual_income,
    )
    monthly_surplus = (
        post_purchase_monthly_income
        - post_purchase_monthly_expense
        - other_existing_monthly_debt_service
        - actual_pmt
    )
    return candidate_dsr <= safe_dsr and monthly_surplus >= buffer_target


def shortest_serviceable_months(
    *,
    principal: Decimal,
    annual_rate: Decimal,
    maximum_months: int,
    annual_income: Decimal,
    existing_annual_debt_service: Decimal,
    safe_dsr: Decimal,
    post_purchase_monthly_income: Decimal,
    post_purchase_monthly_expense: Decimal,
    other_existing_monthly_debt_service: Decimal,
    buffer_target: Decimal,
    dsr_annual_rate: Decimal | None = None,
    minimum_months: int = 1,
) -> int | None:
    """같은 금액을 갚을 수 있는 **가장 짧은 기간**. 없으면 ``None``.

    왜 짧은 쪽을 찾는가:
        원리금균등에서 총이자는 기간에 대해 단조증가한다. 3억을 30년에 걸쳐
        갚으면 이자가 2억을 넘지만 20년이면 그보다 훨씬 적다. 만기를 요청값
        그대로 쓰면 **갚을 수 있는데도 필요 이상으로 오래 갚는다.**

    무엇이 "현실적"인가:
        기간을 줄이면 월 상환액이 오르고 DSR과 현금흐름이 동시에 빠듯해진다.
        그래서 판정은 ``loan_max``와 같은 식(``term_is_serviceable``)을 쓴다.
        더 느슨한 기준으로 짧은 기간을 권하면 **실행할 수 없는 계획**이 된다.

    단조성:
        기간이 늘면 월 상환액은 줄고, DSR도 현금흐름도 함께 완화된다. 따라서
        실행가능 여부는 기간에 대해 단조라 이분 탐색이 성립한다.

    ``None``을 돌려주는 경우:
        최대 기간으로도 갚지 못하는 금액이다. 그때는 **기간이 아니라 금액이
        문제**이므로, 임의로 기간을 늘려 답을 만들지 않는다.
    """
    if maximum_months < minimum_months:
        raise ValueError("maximum_months는 minimum_months보다 작을 수 없습니다.")
    _require_positive(minimum_months, "minimum_months")

    def serviceable(months: int) -> bool:
        return term_is_serviceable(
            principal=principal,
            annual_rate=annual_rate,
            months=months,
            annual_income=annual_income,
            existing_annual_debt_service=existing_annual_debt_service,
            safe_dsr=safe_dsr,
            post_purchase_monthly_income=post_purchase_monthly_income,
            post_purchase_monthly_expense=post_purchase_monthly_expense,
            other_existing_monthly_debt_service=other_existing_monthly_debt_service,
            buffer_target=buffer_target,
            dsr_annual_rate=dsr_annual_rate,
        )

    # 최대 기간으로도 안 되면 더 짧은 기간은 볼 것도 없다.
    if not serviceable(maximum_months):
        return None
    if serviceable(minimum_months):
        return minimum_months

    # 여기서 lo는 "안 되는" 마지막 값, hi는 "되는" 첫 값의 상한이다.
    lo, hi = minimum_months, maximum_months
    while hi - lo > 1:
        middle = (lo + hi) // 2
        if serviceable(middle):
            hi = middle
        else:
            lo = middle
    return hi


def total_interest(principal: Decimal, annual_rate: Decimal, months: int) -> Decimal:
    """원리금균등 총이자 = 월 상환액 × 기간 − 원금.

    기간을 줄여 얼마를 아끼는지 보여줄 때 쓴다. 상환 스케줄을 펼치지 않고도
    총액은 이 곱셈으로 정확하다.
    """
    return pmt(principal, annual_rate, months) * Decimal(months) - principal
