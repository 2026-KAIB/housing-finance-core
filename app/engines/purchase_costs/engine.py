"""Conservative minimum acquisition-cost estimate for a supported home purchase."""

from decimal import Decimal

from app.engines.purchase_costs.formulas import (
    acquisition_tax_rate,
    brokerage_fee_upper_bound,
    floor_won,
    local_education_tax_rate,
    resolve_national_housing_scale,
)
from app.engines.purchase_costs.models import (
    CostComponent,
    CostComponentStatus,
    PurchaseCostEngineStatus,
    PurchaseCostInput,
    PurchaseCostResult,
)
from app.engines.purchase_costs.policy import (
    DEFAULT_PURCHASE_COST_POLICY,
    PurchaseCostPolicy,
)


def _component(
    code: str,
    status: CostComponentStatus,
    amount: Decimal,
    *,
    rate: Decimal | None = None,
    basis: str | None = None,
) -> CostComponent:
    return CostComponent(
        code=code,
        status=status,
        amount=amount,
        rate=rate,
        basis=basis,
    )


def _unknown(code: str, basis: str) -> CostComponent:
    return CostComponent(
        code=code,
        status=CostComponentStatus.UNKNOWN,
        amount=None,
        basis=basis,
    )


def _unknown_tax_components(reason: str) -> tuple[CostComponent, ...]:
    return (
        _unknown("acquisition_tax", reason),
        _unknown("local_education_tax", reason),
        _unknown("rural_special_tax", reason),
    )


def _tax_scope(
    request: PurchaseCostInput,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    missing: list[str] = []
    reasons: list[str] = []
    for name, value in (
        ("buyer_is_corporation", request.buyer_is_corporation),
        (
            "household_home_count_after_purchase",
            request.household_home_count_after_purchase,
        ),
        ("is_registered_housing", request.is_registered_housing),
        ("is_luxury_home", request.is_luxury_home),
    ):
        if value is None:
            missing.append(name)

    if missing:
        return False, tuple(missing), ()
    if request.buyer_is_corporation:
        reasons.append("법인 취득은 v1 취득세 계산 범위에 포함되지 않습니다.")
    if request.household_home_count_after_purchase != 1:
        reasons.append("일반 1주택 외 취득은 v1 취득세 계산 범위에 포함되지 않습니다.")
    if request.is_registered_housing is not True:
        reasons.append("주택으로 확인되지 않은 부동산은 v1 계산 범위에 포함되지 않습니다.")
    if request.is_luxury_home:
        reasons.append("고급주택 중과는 v1 취득세 계산 범위에 포함되지 않습니다.")
    return not reasons, (), tuple(reasons)


def estimate_purchase_costs(
    request: PurchaseCostInput,
    *,
    policy: PurchaseCostPolicy = DEFAULT_PURCHASE_COST_POLICY,
) -> PurchaseCostResult:
    """Estimate known statutory costs without treating missing costs as zero."""

    missing_inputs: list[str] = []
    reasons: list[str] = []
    assumptions: list[str] = [
        "취득세 감면은 적용하지 않은 감면 전 금액입니다.",
        "중개보수는 실제 협의액이 아니라 주택 매매 법정 상한 기준입니다.",
        "세액과 보수는 원 단위 미만을 버린 추정값이며 실제 신고액과 다를 수 있습니다.",
    ]

    if not policy.supports(request.as_of):
        reason = (
            f"정책 검증 범위는 {policy.effective_start.isoformat()}부터 "
            f"{policy.verified_through.isoformat()}까지입니다."
        )
        unknown = _unknown_tax_components(reason)
        brokerage = _unknown("brokerage_fee_upper_bound", reason)
        brokerage_vat = _unknown("brokerage_vat", reason)
        registration = _unknown("registration_and_legal_costs", reason)
        return PurchaseCostResult(
            as_of=request.as_of,
            policy_version=policy.version,
            status=PurchaseCostEngineStatus.POLICY_OUT_OF_RANGE,
            purchase_price=request.purchase_price,
            acquisition_tax=unknown[0],
            local_education_tax=unknown[1],
            rural_special_tax=unknown[2],
            brokerage_fee_upper_bound=brokerage,
            brokerage_vat=brokerage_vat,
            registration_and_legal_costs=registration,
            known_ancillary_costs=Decimal(0),
            minimum_total_purchase_cost=request.purchase_price,
            total_ancillary_costs=None,
            total_purchase_cost=None,
            missing_inputs=("purchase_cost_policy",),
            reasons=(reason,),
            assumptions=tuple(assumptions),
            policy_sources=policy.sources,
        )

    tax_supported, tax_missing, tax_unsupported = _tax_scope(request)
    missing_inputs.extend(tax_missing)
    reasons.extend(tax_unsupported)
    if tax_supported:
        acquisition_rate = acquisition_tax_rate(
            request.purchase_price,
            policy=policy,
        )
        acquisition_tax = _component(
            "acquisition_tax",
            CostComponentStatus.ESTIMATED,
            floor_won(request.purchase_price * acquisition_rate),
            rate=acquisition_rate,
            basis="지방세법 제11조제1항제8호 일반 주택 유상거래 세율",
        )
        education_rate = local_education_tax_rate(
            acquisition_rate,
            policy=policy,
        )
        local_education_tax = _component(
            "local_education_tax",
            CostComponentStatus.ESTIMATED,
            floor_won(request.purchase_price * education_rate),
            rate=education_rate,
            basis="지방세법 제151조제1항제1호",
        )
        is_national_scale = resolve_national_housing_scale(
            request.exclusive_area_m2,
            override=request.is_national_housing_scale_override,
        )
        if is_national_scale is None:
            rural_special_tax = _unknown(
                "rural_special_tax",
                "국민주택규모 여부를 확정할 수 없습니다.",
            )
            missing_inputs.append("is_national_housing_scale")
        elif is_national_scale:
            rural_special_tax = _component(
                "rural_special_tax",
                CostComponentStatus.NOT_APPLICABLE,
                Decimal(0),
                rate=Decimal(0),
                basis="농어촌특별세법상 서민주택 비과세",
            )
        else:
            rural_special_tax = _component(
                "rural_special_tax",
                CostComponentStatus.ESTIMATED,
                floor_won(request.purchase_price * policy.rural_special_tax_rate),
                rate=policy.rural_special_tax_rate,
                basis="농어촌특별세법 제5조제1항제6호",
            )
    else:
        tax_reason = (
            "취득세 적용 사실이 부족합니다."
            if tax_missing
            else "v1이 지원하지 않는 취득세 적용 범위입니다."
        )
        acquisition_tax, local_education_tax, rural_special_tax = _unknown_tax_components(
            tax_reason
        )

    if request.is_registered_housing is True:
        fee, fee_rate, fee_cap = brokerage_fee_upper_bound(
            request.purchase_price,
            brackets=policy.brokerage_brackets,
        )
        cap_note = f", 한도 {fee_cap}원" if fee_cap is not None else ""
        brokerage_fee = _component(
            "brokerage_fee_upper_bound",
            CostComponentStatus.ESTIMATED,
            fee,
            rate=fee_rate,
            basis=f"공인중개사법 시행규칙 별표 1 상한요율{cap_note}",
        )
        vat_rate = (
            request.brokerage_vat_rate_override
            if request.brokerage_vat_rate_override is not None
            else policy.brokerage_vat_rate
        )
        brokerage_vat = _component(
            "brokerage_vat",
            CostComponentStatus.ESTIMATED,
            floor_won(fee * vat_rate),
            rate=vat_rate,
            basis="중개보수에 별도 부과될 수 있는 부가가치세의 보수적 추정",
        )
        if request.brokerage_vat_rate_override is None:
            assumptions.append(
                f"중개보수 부가가치세율은 보수적으로 {vat_rate * 100}%를 적용했습니다."
            )
    else:
        brokerage_reason = (
            "주택 여부가 필요합니다."
            if request.is_registered_housing is None
            else "주택 외 중개보수는 v1 계산 범위에 포함되지 않습니다."
        )
        brokerage_fee = _unknown("brokerage_fee_upper_bound", brokerage_reason)
        brokerage_vat = _unknown("brokerage_vat", brokerage_reason)
        if request.is_registered_housing is None:
            missing_inputs.append("is_registered_housing")

    if request.registration_and_legal_costs is None:
        registration = _unknown(
            "registration_and_legal_costs",
            "등기·법무·채권 관련 비용은 사용자 견적 또는 별도 계산이 필요합니다.",
        )
        missing_inputs.append("registration_and_legal_costs")
    else:
        registration = _component(
            "registration_and_legal_costs",
            CostComponentStatus.PROVIDED,
            request.registration_and_legal_costs,
            basis="사용자 또는 외부 견적 입력",
        )

    components = (
        acquisition_tax,
        local_education_tax,
        rural_special_tax,
        brokerage_fee,
        brokerage_vat,
        registration,
    )
    known_ancillary = sum(
        (component.amount for component in components if component.amount is not None),
        Decimal(0),
    )
    all_known = all(component.amount is not None for component in components)
    total_ancillary = known_ancillary if all_known else None
    total_purchase = (
        request.purchase_price + total_ancillary if total_ancillary is not None else None
    )

    if tax_unsupported:
        status = PurchaseCostEngineStatus.UNSUPPORTED
    elif all_known:
        status = PurchaseCostEngineStatus.COMPLETE
    else:
        status = PurchaseCostEngineStatus.PARTIAL

    return PurchaseCostResult(
        as_of=request.as_of,
        policy_version=policy.version,
        status=status,
        purchase_price=request.purchase_price,
        acquisition_tax=acquisition_tax,
        local_education_tax=local_education_tax,
        rural_special_tax=rural_special_tax,
        brokerage_fee_upper_bound=brokerage_fee,
        brokerage_vat=brokerage_vat,
        registration_and_legal_costs=registration,
        known_ancillary_costs=known_ancillary,
        minimum_total_purchase_cost=request.purchase_price + known_ancillary,
        total_ancillary_costs=total_ancillary,
        total_purchase_cost=total_purchase,
        missing_inputs=tuple(dict.fromkeys(missing_inputs)),
        reasons=tuple(dict.fromkeys(reasons)),
        assumptions=tuple(dict.fromkeys(assumptions)),
        policy_sources=policy.sources,
    )
