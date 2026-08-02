#!/usr/bin/env python
"""페르소나 20명의 구매 가능성을 엔진으로 판정한다(읽기 전용).

    .venv/bin/python scripts/check_persona_affordability.py

설계 문서(docs/superpowers/specs/2026-08-01-persona-home-purchase-design.md)
2.3의 "가능 3명"은 LTV 70%·DSR 40%만 본 손계산이다. 스트레스 가산금리와
Rule Pack 자격을 반영한 실제 판정을 확인해 문서에 반영하기 위한 도구다.

이 스크립트는 페르소나 JSON을 읽기만 하고, 아무 것도 쓰거나 재생성하지 않는다.

작업 계획 초안(task-5-brief.md)의 예시 코드에는 실행하면 안 되는 결함이 두 개
있었다. 둘 다 여기서 고쳤다:

1. **목표 시점을 전원 2028-07-01로 하드코딩.** 실제로는 페르소나마다
   ``target_move_in_ym``이 다르다(20명 중 10명만 202807이고 나머지는
   202901·202801·202707·202907로 갈린다). 하드코딩하면 축적 기간이 틀려
   판정이 달라진다. 이 스크립트는 각 페르소나 자신의 ``target_move_in_ym``을
   읽어 그 달 1일로 변환한다.
2. **부족액을 ``result.loan_simulation``에서 읽으려 한 것.** 그 구간의
   ``result``는 ``LoanSimulationResult``를 그대로 JSON화한 것이라 상품별
   ``executable``/``rejected``/... 목록만 있고 ``funding_shortfall`` 키 자체가
   없다 — 항상 ``None``이 되어 전원이 "확인불가"로 잘못 찍힌다. 보고서 5절
   (``form.py``의 ``_shortfall_and_extension``)이 실제로 읽는 값은
   ``result.recommendation.result["loan"]["funding_shortfall"]``이다
   (``app/reports/context.py``의 ``_recommendation_parts``가 종합추천이 완료되면
   그 구간의 대출 사실을 ``sections.loan``으로 승격한다). 이 스크립트도 같은
   경로를 읽는다.
"""

import glob
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from app.regulations.mortgage_limits import HousingStatus
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SectionRunStatus,
    SimulationInput,
    UserProfile,
)
from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)
from app.services.simulation_orchestrator import run_simulation

AS_OF = date(2026, 8, 1)
MYDATA = os.path.join("app", "data_pipeline", "mydata")

# 종합추천의 대출 상태 중 "숫자는 나왔지만 확정 판정이 아님"을 뜻하는 값들.
# UNKNOWN은 입력을 확정 못 해 판정을 못 낸 것이고, NOT_REQUESTED는 대출 절
# 자체를 요청하지 않은 것이다 — 둘 다 "부족액이 0보다 크다"는 뜻이 아니므로
# 미달로 뭉개면 안 된다(§22.1).
_UNRESOLVED_LOAN_STATUSES = {"UNKNOWN", "NOT_REQUESTED"}


def _target_date(profile: dict) -> date:
    """페르소나 자신의 ``target_move_in_ym``(YYYYMM)을 그 달 1일로 바꾼다.

    브리핑 초안처럼 2028-07-01을 전원에게 하드코딩하지 않는다 — 20명 중
    10명만 그 값이고 나머지는 다른 달을 목표로 한다.
    """
    ym = str(profile["target_move_in_ym"])
    return date(int(ym[:4]), int(ym[4:6]), 1)


def _load_generation_metadata(directory: str) -> dict:
    """``user_profile.json``과 같은 폴더의 ``generation_metadata.json``을 읽는다.

    없으면 빈 dict를 돌려준다 — 20명 전원이 이 파일을 갖고 있지만, 없는
    경우에도 호출부가 폴백 하나를 잃을 뿐 죽지 않게 한다.
    """
    path = os.path.join(directory, "generation_metadata.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_financial_fact(
    profile: dict,
    metadata: dict,
    field: str,
) -> tuple[Decimal | None, str]:
    """``profile``에 없으면 ``generation_metadata.provided_facts``에서 찾는다.

    이전에는 ``profile.get(field, 0)``으로 결측을 조용히 0으로 뭉갰다 —
    ``persona_e_college_student_basic``은 손으로 작성한 유일한 페르소나라
    ``user_profile.json``에 ``current_assets``/``monthly_debt_payment`` 키
    자체가 없는데, 이 값이 유동자산 0원으로 계산되어 부족액이 실제보다
    1,000,000원(계좌 잔액) 더 크게 나왔다.

    ``current_assets``는 여기서 실제 값(1,000,000원)을 회복한다 —
    ``generation_metadata.json``의 ``provided_facts.current_assets``가 그
    페르소나 본인이 준 사실이고, 계좌 스냅샷(``bank_003_deposit_detail_*.json``의
    ``balance_amt``)과도 일치한다. ``monthly_debt_payment``는
    ``provided_facts.has_loans is False``일 때만 확정 0(§22.1의 "해당 없음")으로
    돌려준다 — 부채가 있는데 상환액 숫자만 없는 경우까지 0으로 채우지 않는다.

    두 출처 어디에도 없으면 (None, 사유)를 돌려주고 호출부가 확인불가로
    분류하게 한다. 절대 조용히 0을 대신 넣지 않는다.
    """
    if profile.get(field) is not None:
        return Decimal(str(profile[field])), ""

    provided_facts = metadata.get("provided_facts", {})
    if provided_facts.get(field) is not None:
        return Decimal(str(provided_facts[field])), ""

    if field == "monthly_debt_payment" and provided_facts.get("has_loans") is False:
        return Decimal(0), ""

    reason = (
        f"{field} 필드가 user_profile.json과 generation_metadata.json "
        "어디에도 없음"
    )
    return None, reason


def build_input(
    profile: dict,
    liquid_assets: Decimal,
    monthly_debt_payment: Decimal,
) -> SimulationInput:
    return SimulationInput(
        profile=UserProfile(
            persona_name=profile.get("persona_type"),
            age=profile["age_as_of"],
            household_size=profile["household_size"],
            annual_income=Decimal(profile["annual_income_verified"]),
            employment_type=profile["employment_type"],
            is_first_home_buyer=profile["is_first_home_buyer"],
            is_married=profile["marital_status"] != "single",
            region_code=profile["target_region"],
        ),
        housing_goal=HousingGoal(
            target_amount=Decimal(profile["target_price"]),
            target_date=_target_date(profile),
            region_code=profile["target_region"],
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal(profile["monthly_income"]),
            monthly_expense=Decimal(profile["monthly_average_expense"]),
            liquid_assets=liquid_assets,
            monthly_debt_payment=monthly_debt_payment,
        ),
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal(profile["monthly_average_expense"]),
        ),
    )


def _loan_facts(result) -> tuple[dict | None, str]:
    """종합추천 구간에서 대출 사실 딕셔너리를 꺼낸다.

    반환값의 두 번째 값은 facts가 ``None``일 때의 원인 설명이다(§22.1 —
    "무엇을 알려주면 계산되는지"로 읽혀야 한다는 규약).
    """
    recommendation = result.recommendation
    if recommendation.run_status is not SectionRunStatus.COMPLETED:
        return None, "종합추천 구간이 실행되지 않음(NOT_RUN)"
    if recommendation.result is None:
        return None, "종합추천 구간에 result가 없음"
    loan_facts = recommendation.result.get("loan")
    if not isinstance(loan_facts, dict):
        return None, "종합추천 결과에 loan 키가 없음"
    return loan_facts, ""


def classify(result) -> tuple[str, str, Decimal | None, dict | None]:
    """(구매가능|미달|확인불가), 사유, 부족액, 대출 facts를 돌려준다.

    세 상태를 뭉개지 않는다:
      - 구매가능: 부족액이 계산됐고 0 이하
      - 미달    : 부족액이 계산됐고 0보다 큼(스트레스 가산금리·상품별 한도·
                  Rule Pack 자격 탈락으로 한도가 0인 경우도 포함 — 이것도
                  "계산해 보니 0"이라는 확정 결과이지 모름이 아니다)
      - 확인불가: 종합추천이 안 돌았거나, loan facts가 없거나, 상태가
                  UNKNOWN/NOT_REQUESTED거나, funding_shortfall 키 자체가 없음
    """
    loan_facts, reason = _loan_facts(result)
    if loan_facts is None:
        return "확인불가", reason, None, None

    status = str(loan_facts.get("status"))
    if status in _UNRESOLVED_LOAN_STATUSES:
        return "확인불가", f"대출 상태={status}", None, loan_facts

    raw_shortfall = loan_facts.get("funding_shortfall")
    if raw_shortfall is None:
        return "확인불가", "funding_shortfall 키가 없음", None, loan_facts

    try:
        shortfall = Decimal(str(raw_shortfall))
    except InvalidOperation:
        reason = f"funding_shortfall 값을 해석할 수 없음: {raw_shortfall!r}"
        return "확인불가", reason, None, loan_facts

    verdict = "구매가능" if shortfall <= 0 else "미달"
    return verdict, "", shortfall, loan_facts


def main() -> int:
    try:
        candidates = load_configured_loan_candidates(as_of=AS_OF)
    except LoanProductCatalogUnavailable as exc:
        print("BLOCKED: 대출 상품 카탈로그를 불러올 수 없습니다.")
        print(f"  원인: {exc}")
        print(
            "  기본 설정(LOAN_PRODUCT_PROVIDER=json)에서는 DB가 아니라 "
            "sample_data/loan_products/*.json을 읽습니다."
        )
        print(
            "  LOAN_PRODUCT_PROVIDER/LOAN_PRODUCT_BASE_JSON_PATH/"
            "LOAN_PRODUCT_OPTION_JSON_PATH 설정과 그 JSON 파일의 존재를 확인하세요."
        )
        print(
            "  provider를 database로 바꿔 쓰는 환경에서만 DB 터널이 필요합니다."
        )
        print("  값을 추정해 문서에 적지 않습니다.")
        return 1

    rows = []
    for path in sorted(glob.glob(f"{MYDATA}/persona_*college_student*/user_profile.json")):
        directory = os.path.dirname(path)
        with open(path, encoding="utf-8") as fh:
            profile = json.load(fh)
        metadata = _load_generation_metadata(directory)

        liquid_assets, liquid_reason = _resolve_financial_fact(
            profile, metadata, "current_assets"
        )
        monthly_debt_payment, debt_reason = _resolve_financial_fact(
            profile, metadata, "monthly_debt_payment"
        )
        if liquid_assets is None or monthly_debt_payment is None:
            # §22.1 — 결측을 0으로 뭉개지 않는다. 시뮬레이션 자체를 돌리지
            # 않고 확인불가로 남기며, 어떤 필드가 없는지 이름으로 남긴다.
            missing_reason = "; ".join(
                reason for reason in (liquid_reason, debt_reason) if reason
            )
            rows.append(
                {
                    "name": os.path.basename(directory),
                    "target_price": int(profile["target_price"]),
                    "target_ym": profile["target_move_in_ym"],
                    "verdict": "확인불가",
                    "reason": missing_reason,
                    "shortfall": None,
                    "status": None,
                }
            )
            continue

        result = run_simulation(
            build_input(profile, liquid_assets, monthly_debt_payment),
            simulation_id=uuid4(),
            as_of=AS_OF,
            calculated_at=datetime.now(tz=UTC),
            loan_candidates=candidates,
        )
        verdict, reason, shortfall, loan_facts = classify(result)
        rows.append(
            {
                "name": os.path.basename(directory),
                "target_price": int(profile["target_price"]),
                "target_ym": profile["target_move_in_ym"],
                "verdict": verdict,
                "reason": reason,
                "shortfall": shortfall,
                "status": None if loan_facts is None else loan_facts.get("status"),
            }
        )

    header = f"{'페르소나':44}{'목표시점':>10}{'목표가':>14}{'부족액':>18}  대출상태  판정"
    print(header)
    for row in rows:
        if row["shortfall"] is None:
            shortfall_text = "확인불가"
        else:
            shortfall_text = "없음" if row["shortfall"] <= 0 else f"{row['shortfall']:,.0f}"
        print(
            f"{row['name']:44}{str(row['target_ym']):>10}{row['target_price']:>14,}"
            f"{shortfall_text:>18}  {str(row['status']):8}  {row['verdict']}"
        )

    buyable = [r for r in rows if r["verdict"] == "구매가능"]
    short = [r for r in rows if r["verdict"] == "미달"]
    unknown = [r for r in rows if r["verdict"] == "확인불가"]

    print(f"\n구매 가능 {len(buyable)}명 / 미달 {len(short)}명 / 확인불가 {len(unknown)}명")
    if unknown:
        print("확인불가 상세(미달로 뭉개지 않음):")
        for row in unknown:
            print(f"  - {row['name']}: {row['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
