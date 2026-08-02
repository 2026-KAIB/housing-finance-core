#!/usr/bin/env python
"""신규 페르소나 4명이 기존 대학생 20명과 다른 판정으로 갈리는지 확인한다(읽기 전용).

    .venv/bin/python scripts/check_new_personas_affordability.py

check_persona_affordability.py와 같은 판정 로직(build_input/classify)을 그대로
쓰되, 대상 폴더만 "대학생 20명" 대신 "대학생 20명 + 신규 4명" 전체로 넓힌다.
새 파일을 쓰거나 재생성하지 않는다.
"""

import glob
import json
import os
from datetime import UTC, date, datetime
from uuid import uuid4

from check_persona_affordability import (
    _load_generation_metadata,
    _resolve_financial_fact,
    build_input,
    classify,
)

from app.services.loan_product_catalog import (
    LoanProductCatalogUnavailable,
    load_configured_loan_candidates,
)
from app.services.simulation_orchestrator import run_simulation

AS_OF = date(2026, 8, 1)
MYDATA = os.path.join("app", "data_pipeline", "mydata")
NEW_PERSONA_GLOBS = [
    f"{MYDATA}/persona_*college_student*/user_profile.json",
    f"{MYDATA}/persona_y[1-4]_*/user_profile.json",
]


def main() -> int:
    try:
        candidates = load_configured_loan_candidates(as_of=AS_OF)
    except LoanProductCatalogUnavailable as exc:
        print(f"BLOCKED: 대출 상품 카탈로그를 불러올 수 없습니다: {exc}")
        return 1

    paths = sorted({p for pat in NEW_PERSONA_GLOBS for p in glob.glob(pat)})
    rows = []
    for path in paths:
        directory = os.path.dirname(path)
        name = os.path.basename(directory)
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
            reason = "; ".join(r for r in (liquid_reason, debt_reason) if r)
            rows.append((name, "확인불가", reason, None))
            continue

        result = run_simulation(
            build_input(profile, liquid_assets, monthly_debt_payment),
            simulation_id=uuid4(),
            as_of=AS_OF,
            calculated_at=datetime.now(tz=UTC),
            loan_candidates=candidates,
        )
        verdict, reason, shortfall, _facts = classify(result)
        rows.append((name, verdict, reason, shortfall))

    is_new = lambda n: n.startswith("persona_y")  # noqa: E731
    header = f"{'페르소나':44}{'구분':>8}{'판정':>8}{'부족액':>18}"
    print(header)
    for name, verdict, reason, shortfall in rows:
        shortfall_text = (
            "확인불가" if shortfall is None else ("없음" if shortfall <= 0 else f"{shortfall:,.0f}")
        )
        tag = "[신규]" if is_new(name) else "[학생]"
        print(f"{name:44}{tag:>8}{verdict:>8}{shortfall_text:>18}  {reason}")

    student_verdicts = {v for n, v, *_ in rows if not is_new(n)}
    new_rows = [(n, v) for n, v, *_ in rows if is_new(n)]
    print("\n기존 학생 20명의 판정 종류:", student_verdicts)
    print("신규 4명의 판정:", new_rows)
    diff = [n for n, v in new_rows if v not in student_verdicts]
    same = [n for n, v in new_rows if v in student_verdicts]
    print(f"\n기존 학생 판정과 겹치지 않는 신규 페르소나: {diff or '없음'}")
    print(f"기존 학생 판정과 같은 카테고리인 신규 페르소나: {same or '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
