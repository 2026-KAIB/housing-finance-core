"""SSOT §8의 시나리오별 목표 주택가격과 총 구매비용을 만든다.

전략 비교 엔진은 미래 가격을 **예측하지 않는다.** 호출자가 근거와 함께 넘긴
값만 쓴다(§15). 이 모듈이 그 근거다 — 변동률을 지어내는 것이 아니라 SSOT
§8.1 **[B-6 확정]** 표를 그대로 적용하고, 각 시나리오에 그 출처를 붙인다.

    현재 가격 유지  0%
    완만한 상승     2%
    보수적 상승     4%
    스트레스        4% + 금리 상승 동시 적용

확률을 붙이지 않는다(§8.3). "몇 개 시나리오를 충족하는지"만 남기며, 어느
시나리오가 더 그럴듯한지 이 모듈도 보고서도 말하지 않는다.

왜 취득 사실이 없으면 만들지 않는가:
    §8.2는 총 구매 필요금액을 ``주택가격 + 취득세 + 중개비 + …``로 정의한다.
    매매가만으로 시나리오를 세우면 필요 자금을 **실제보다 작게** 잡고, 계획이
    실제보다 쉬워 보인다. 부대비용을 확정하지 못하면 시나리오를 만들지 않고
    무엇이 없어서 못 만들었는지만 남긴다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.engines.purchase_costs.engine import estimate_purchase_costs
from app.engines.purchase_costs.models import PurchaseCostInput, PurchaseCostResult
from app.engines.strategy.models import HousingCostScenario
from app.schemas.simulation import AcquisitionCostInput, SimulationInput

SCENARIO_SOURCE = "주택구매 금융컨설팅 공식 설계안 §8.1 [B-6 확정] 시나리오 초기 변동률"

# 1년을 365일로 본다. 목표기간 연수를 정수 연으로 끊으면 11개월과 13개월이 같은
# 배수를 받는다. 지수가 연 단위이므로 일수를 연으로 환산해 넣는다.
_DAYS_PER_YEAR = Decimal(365)

_ACQUISITION_COSTS_MISSING = "acquisition_costs"
_SCENARIO_COST_MISSING = "scenario_total_purchase_cost"


@dataclass(frozen=True)
class _ScenarioRate:
    code: str
    name: str
    annual_rate: Decimal
    is_baseline: bool = False
    extra_assumptions: tuple[str, ...] = ()


HOUSING_SCENARIO_RATES: tuple[_ScenarioRate, ...] = (
    _ScenarioRate(
        code="CURRENT_PRICE",
        name="현재 가격 유지",
        annual_rate=Decimal("0"),
        # 변동률 가정이 없는 유일한 시나리오라 기준선으로 둔다.
        is_baseline=True,
    ),
    _ScenarioRate(code="MODERATE_RISE", name="완만한 상승", annual_rate=Decimal("0.02")),
    _ScenarioRate(code="CONSERVATIVE_RISE", name="보수적 상승", annual_rate=Decimal("0.04")),
    _ScenarioRate(
        code="STRESS",
        name="스트레스",
        annual_rate=Decimal("0.04"),
        extra_assumptions=(
            "가격 축은 보수적 상승과 같습니다. 이 시나리오가 더하는 금리 상승은 "
            "생활 스트레스 구간에서 별도로 적용하며, 총 구매비용에는 반영되지 "
            "않습니다.",
        ),
    ),
)


@dataclass(frozen=True)
class HousingScenarioBuild:
    """만들어진 시나리오와, 만들지 못했다면 그 이유."""

    scenarios: tuple[HousingCostScenario, ...] = ()
    missing_inputs: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    policy_sources: tuple[str, ...] = ()


def _years_between(as_of: date, target_date: date) -> Decimal:
    days = Decimal((target_date - as_of).days)
    return max(days, Decimal(0)) / _DAYS_PER_YEAR


def scenario_price(
    current_price: Decimal,
    *,
    annual_rate: Decimal,
    years: Decimal,
) -> Decimal:
    """§8.1의 ``현재가 × (1 + 변동률)^연수``. 원 단위로 반올림한다."""
    if annual_rate == 0 or years == 0:
        grown = current_price
    else:
        # Decimal에는 실수 지수 거듭제곱이 없다. ln·exp로 돌려도 정밀도가
        # 충분하며, 원 단위로 반올림해 내보내므로 표시값이 흔들리지 않는다.
        growth = ((Decimal(1) + annual_rate).ln() * years).exp()
        grown = current_price * growth
    return grown.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _cost_input(
    price: Decimal,
    *,
    as_of: date,
    acquisition: AcquisitionCostInput,
) -> PurchaseCostInput:
    return PurchaseCostInput(
        as_of=as_of,
        purchase_price=price,
        **acquisition.model_dump(),
    )


def _total_cost(result: PurchaseCostResult) -> Decimal | None:
    return result.total_purchase_cost


def build_housing_cost_scenarios(
    payload: SimulationInput,
    *,
    as_of: date,
) -> HousingScenarioBuild:
    """§8.1 네 시나리오를 총 구매비용까지 확정해 만든다."""

    acquisition = payload.acquisition_costs
    if acquisition is None:
        return HousingScenarioBuild(
            missing_inputs=(_ACQUISITION_COSTS_MISSING,),
            reasons=(
                "총 구매비용을 확정할 취득 사실(법인 여부·주택 수·주택 해당 여부 등)이 "
                "없어 시나리오별 목표 주택가격을 만들지 않았습니다. 매매가만으로 "
                "시나리오를 세우면 필요 자금을 실제보다 작게 잡습니다.",
            ),
        )

    current_price = payload.housing_goal.resolved_target_amount
    years = _years_between(as_of, payload.housing_goal.target_date)
    early = estimate_purchase_costs(
        _cost_input(current_price, as_of=as_of, acquisition=acquisition)
    )
    early_total = _total_cost(early)
    if early_total is None:
        return HousingScenarioBuild(
            missing_inputs=(_SCENARIO_COST_MISSING, *early.missing_inputs),
            reasons=(
                "현재 가격 기준 총 구매비용을 확정하지 못해 시나리오를 만들지 "
                "않았습니다.",
                *early.reasons,
            ),
            policy_sources=early.policy_sources,
        )

    scenarios: list[HousingCostScenario] = []
    missing: list[str] = []
    reasons: list[str] = []
    sources = list(early.policy_sources)
    for rate in HOUSING_SCENARIO_RATES:
        price = scenario_price(current_price, annual_rate=rate.annual_rate, years=years)
        later = estimate_purchase_costs(
            _cost_input(price, as_of=as_of, acquisition=acquisition)
        )
        later_total = _total_cost(later)
        if later_total is None:
            missing.extend(later.missing_inputs)
            reasons.append(
                f"{rate.name} 시나리오의 총 구매비용을 확정하지 못해 제외했습니다."
            )
            continue
        sources.extend(later.policy_sources)
        scenarios.append(
            HousingCostScenario(
                code=rate.code,
                name=rate.name,
                early_purchase_total_cost=early_total,
                asset_accumulation_total_cost=later_total,
                is_baseline=rate.is_baseline,
                basis_date=as_of,
                source_note=SCENARIO_SOURCE,
                assumptions=(
                    f"연간 변동률 {rate.annual_rate * 100:.0f}%를 "
                    f"{years.quantize(Decimal('0.01'))}년 적용했습니다.",
                    "부대비용은 목표 시점의 세율·요율이 아니라 산출 기준일의 "
                    "값으로 계산했습니다. 세율이 바뀌면 결과가 달라집니다.",
                    *rate.extra_assumptions,
                ),
            )
        )

    if not scenarios:
        return HousingScenarioBuild(
            missing_inputs=tuple(dict.fromkeys([_SCENARIO_COST_MISSING, *missing])),
            reasons=tuple(reasons),
            policy_sources=tuple(dict.fromkeys(sources)),
        )

    return HousingScenarioBuild(
        scenarios=tuple(scenarios),
        missing_inputs=tuple(dict.fromkeys(missing)),
        reasons=tuple(reasons),
        assumptions=(
            f"시나리오 변동률은 {SCENARIO_SOURCE}의 값입니다.",
            "시나리오에 확률을 붙이지 않습니다. 몇 개 시나리오를 충족하는지만 "
            "제시합니다(§8.3).",
        ),
        policy_sources=tuple(dict.fromkeys(sources)),
    )


def scenario_target_amounts(
    scenarios: Sequence[HousingCostScenario],
) -> dict[str, Decimal]:
    """시나리오 코드 → 목표 시점의 총 구매 필요금액. 보고서 표시용."""
    return {
        scenario.code: scenario.asset_accumulation_total_cost for scenario in scenarios
    }


__all__ = [
    "HOUSING_SCENARIO_RATES",
    "SCENARIO_SOURCE",
    "HousingScenarioBuild",
    "build_housing_cost_scenarios",
    "scenario_price",
    "scenario_target_amounts",
]
