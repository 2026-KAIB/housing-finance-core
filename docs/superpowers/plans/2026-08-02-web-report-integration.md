# 웹 보고서 연동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step 1 입력 폼을 확장해 보고서의 대출·전략비교 절을 열고, 사용자가 입력한 값으로 실제 계산을 돌려 대시보드 하단에 보고서 PDF를 인라인으로 띄운다.

**Architecture:** 위저드가 폼 값을 `sessionStorage`에 넘기고, 대시보드(클라이언트 컴포넌트)가 그 값으로 `SimulationInput`을 만들어 두 개의 독립된 백엔드 호출을 발사한다 — 빠른 `POST /api/v1/simulations`가 카드를, 느린 `POST /api/v1/reports?format=pdf`가 하단 뷰어를 채운다. 보고서는 응답 헤더 `X-Report-Id`를 받아 `GET /api/v1/reports/{id}.pdf`를 iframe에 물린다.

**Tech Stack:** core는 Python 3.12 / FastAPI / pydantic / weasyprint. web은 Next.js 16 / TypeScript / zod / react-hook-form / vitest + @testing-library/react.

**설계 문서:** `docs/superpowers/specs/2026-08-02-web-report-integration-design.md`

## 저장소 두 곳

| 이름 | 경로 | 브랜치 |
| --- | --- | --- |
| core | `/Users/programming/housing-finance-system/housing-finance-core` | `jpyo` |
| web | `/Users/programming/housing-finance-system/housing-finance-web` | `feature/frontend-prototype` |

루트(`housing-finance-system`)는 git 저장소가 아니다. 커밋은 각 저장소 안에서 한다.

## Global Constraints

- **모르는 값을 느슨한 쪽으로 채우지 않는다.** 0·기본값·비규제로 물러서면 한도가 커지거나 계획이 쉬워 보인다. 확정 못 하면 UNKNOWN을 반환하고 **어떤 필드가 없는지 이름으로** 남긴다.
- **0과 모름, 모름과 "해당 없음"을 뭉개지 않는다.** 한도 0원과 한도 미상은 다른 상태다.
- **판정을 받지 못한 상태는 통과가 아니다.**
- 금액은 원(KRW) 정수. 기간은 개월. 표시용 반올림과 계산용 값을 분리한다.
- `.env`에 DB 접속정보와 API 키가 들어간다. **읽지 말고 값을 출력하지 말 것.** 오류 메시지에도 DSN·사용자명을 넣지 않는다.
- `selected_23_products.json`은 추적하지 않는 원천 데이터다. **커밋하지 말 것.** core에서는 `git add -A ':!selected_23_products.json'`.
- **`ruff format`을 디렉터리 전체에 돌리지 말 것.** 린트는 손댄 파일에만 건다: `python -m ruff check <파일>`.
- `main`에 직접 커밋하지 않는다. 위 표의 브랜치에서 작업한다.
- 웹 픽스처(`src/mocks/fixtures/`)를 손으로 고치지 않는다. 이 계획은 픽스처를 바꾸지 않는다.
- **페르소나 재무 데이터와 `tests/data_pipeline/test_college_student_goals.py`를 건드리지 않는다.** 이 계획은 `app/data_pipeline/`에 손대지 않는다.
- 사용자에게 보이는 문구는 한국어로 쓴다.

## 기본값 — 전 과제 공통

이 네 값은 여러 과제에 반복해서 나온다. **어디서든 같은 값을 쓴다.**

| 필드 | 값 | 반대로 두면 |
| --- | --- | --- |
| `months` | `360` | — (사용자가 고르는 값) |
| `housing_status` | `"NO_HOUSE"` | 생애최초는 LTV 70%, 무주택은 40%. 유리한 쪽을 기본값으로 두면 한도가 커진다 |
| `monthly_essential_expense` | `monthly_average_expense`와 **같은 값** | 필수생활비가 작을수록 Buffer가 작아져 한도가 커진다 |
| `exclusive_area_m2` | `84` | 목표가가 `exclu_use_ar <= 85` 실거래 p05에서 나왔다 |

## 파일 구조

**core**

| 파일 | 책임 |
| --- | --- |
| `app/services/simulation_result.py` (수정) | 저축 절에 정책 재검증 판정을 함께 싣는다 |
| `app/services/simulation_orchestrator.py` (수정) | 이미 들고 있는 `savings_validation`을 조립에 넘긴다 |
| `tests/schemas/test_simulation_result_contract.py` (수정) | 판정 직렬화 검증 |
| `tests/reports/test_pdf_environment.py` (신규) | PDF 렌더러·한글 글꼴 가용성 검증 |

**web**

| 파일 | 책임 |
| --- | --- |
| `src/features/input/form-schema.ts` (수정) | 네 필드 추가, `current_assets` 필수화 |
| `src/features/input/loan-fields.tsx` (신규) | "대출 조건" 입력 3개 |
| `src/features/input/desired-home-panel.tsx` (수정) | 전용면적 입력 |
| `src/features/input/step-input.tsx` (수정) | `LoanFields` 배치 |
| `src/features/input/step-review.tsx` (수정) | 새 값 4개 표시 |
| `src/lib/format/codes.ts` (수정) | `housingStatusLabel`, `loanTermLabel` |
| `src/lib/api/simulation-input.ts` (신규) | 폼값 → `SimulationInput` JSON |
| `src/lib/api/errors.ts` (신규) | HTTP 실패를 화면 문구로 |
| `src/lib/api/client.ts` (신규) | 두 엔드포인트 호출 |
| `src/lib/api/portfolio-result.ts` (신규) | `SimulationResult` → `PortfolioResult` |
| `src/lib/contracts/result.ts` (수정) | `evaluation`을 optional로 |
| `src/features/dashboard/portfolio-status-notice.tsx` (수정) | `evaluation` 없으면 그 줄을 감춤 |
| `src/lib/session/input-handoff.ts` (신규) | 위저드 → 대시보드 폼값 전달 |
| `src/features/input/input-wizard.tsx` (수정) | 제출 시 폼값 저장 |
| `src/features/dashboard/live-dashboard.tsx` (신규) | 두 호출 오케스트레이션 |
| `src/features/dashboard/portfolio-view.tsx` (수정) | 낡은 `edited` 안내 제거 |
| `src/app/dashboard/page.tsx` (수정) | `LiveDashboard` 마운트 |
| `src/features/report/report-viewer.tsx` (신규) | PDF iframe + 상태 4가지 |

## 과제 의존 관계

```
Task 1 (core 직렬화) ─┐
Task 2 (core PDF 환경) ┤
                       ├─→ Task 8 (대시보드) ─→ Task 9 (뷰어)
Task 3 (폼 스키마) ─→ Task 4 (폼 UI)         ↑
      └────────────→ Task 5 (입력 매핑) ─→ Task 6 (클라이언트·결과 매핑) ─→ Task 7 (핸드오프)
```

---

### Task 1: core — 저축 포트폴리오 정책 재검증 직렬화

대시보드가 쓰는 `final_policy_status`·`final_policy_valid`·`validation_reasons`가 `SimulationResult`에 없다. 값은 `SavingsPortfolioOutcome.validation`에 있으나 조립 단계에서 버려진다.

**Files:**
- Modify: `app/services/simulation_result.py`
- Modify: `app/services/simulation_orchestrator.py:417`
- Test: `tests/schemas/test_simulation_result_contract.py`

**Interfaces:**
- Consumes: `SavingsPortfolioPolicyValidation`(`app/data_pipeline/adapters/savings_portfolio_policy_adapter.py:49`) — `status: EvaluationStatus`, `decisions`, `reasons: tuple[str, ...]`, `valid: bool` (property)
- Produces: `SimulationResult.savings_portfolio.result`에 세 키가 추가된다. 절의 `section_schema_version`이 `"savings-portfolio@1.1.0"`이 된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/schemas/test_simulation_result_contract.py` 맨 아래에 추가한다. 파일 상단 import에 두 줄을 더한다:

```python
from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    SavingsPortfolioPolicyValidation,
)
from app.rule_engine.product_packs.models import EvaluationStatus
```

테스트 본문:

```python
def test_savings_section_carries_final_policy_decision() -> None:
    """정책 재검증 판정은 배분과 같은 자리에서 읽혀야 한다.

    판정은 엔진 결과가 아니라 Rule Pack 재검증 결과여서
    ``SavingsPortfolioResult`` 안에 없다. 그러나 소비자에게는 "이 배분이
    정책을 통과했는가"가 배분과 분리될 이유가 없다.
    """
    result = build_simulation_result(
        _input(),
        simulation_id=_SIMULATION_ID,
        as_of=_AS_OF,
        calculated_at=_CALCULATED_AT,
        savings_portfolio_result=_savings_portfolio(),
        savings_policy_validation=SavingsPortfolioPolicyValidation(
            status=EvaluationStatus.PASS,
            decisions=(),
            reasons=("상품 X가 재검증에서 제외됨",),
        ),
    )

    section = result.savings_portfolio
    assert section.section_schema_version == "savings-portfolio@1.1.0"
    assert section.result is not None
    assert section.result["final_policy_status"] == "PASS"
    assert section.result["final_policy_valid"] is True
    assert section.result["validation_reasons"] == ["상품 X가 재검증에서 제외됨"]


def test_savings_section_omits_policy_keys_when_validation_is_absent() -> None:
    """판정을 받지 못한 상태는 통과가 아니다. PASS로 채우지 않는다."""
    result = build_simulation_result(
        _input(),
        simulation_id=_SIMULATION_ID,
        as_of=_AS_OF,
        calculated_at=_CALCULATED_AT,
        savings_portfolio_result=_savings_portfolio(),
    )

    section = result.savings_portfolio
    assert section.result is not None
    assert "final_policy_status" not in section.result
    assert "final_policy_valid" not in section.result
    assert "validation_reasons" not in section.result
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/schemas/test_simulation_result_contract.py -k policy -v`
Expected: FAIL — `build_simulation_result() got an unexpected keyword argument 'savings_policy_validation'`

- [ ] **Step 3: 저축 절 조립 함수를 만든다**

`app/services/simulation_result.py`의 import에 추가한다:

```python
from app.data_pipeline.adapters.savings_portfolio_policy_adapter import (
    SavingsPortfolioPolicyValidation,
)
```

`build_simulation_result` 정의 **바로 위**에 함수를 넣는다:

```python
def _savings_section(
    savings_portfolio_result: SavingsPortfolioResult | None,
    validation: SavingsPortfolioPolicyValidation | None,
) -> CalculationSection:
    """저축 절에 최종 정책 재검증 판정을 함께 싣는다.

    판정은 엔진이 아니라 Rule Pack 재검증이 만든다. 그래서
    ``SavingsPortfolioResult`` 안에 없지만, 소비자에게는 "이 배분이 정책을
    통과했는가"가 배분과 같은 자리에서 읽혀야 한다.

    검증이 없으면 **채우지 않는다.** 판정을 받지 못한 상태는 통과가 아니며,
    빈 자리를 ``PASS``로 메우면 통과와 미판정이 같은 값이 된다.
    """
    section = build_calculation_section(
        savings_portfolio_result,
        section_schema_version="savings-portfolio@1.1.0",
    )
    if section.result is None or validation is None:
        return section
    return section.model_copy(
        update={
            "result": {
                **section.result,
                "final_policy_status": validation.status.value,
                "final_policy_valid": validation.valid,
                "validation_reasons": list(validation.reasons),
            }
        }
    )
```

- [ ] **Step 4: `build_simulation_result`가 그 함수를 쓰게 한다**

시그니처에 인자를 하나 더한다. `savings_portfolio_result` 바로 다음 줄이다:

```python
    savings_portfolio_result: SavingsPortfolioResult | None = None,
    savings_policy_validation: SavingsPortfolioPolicyValidation | None = None,
```

`sections` 딕셔너리에서 `"savings_portfolio"` 항목을 바꾼다:

```python
        "savings_portfolio": _savings_section(
            savings_portfolio_result, savings_policy_validation
        ),
```

- [ ] **Step 5: 오케스트레이터가 판정을 넘기게 한다**

`app/services/simulation_orchestrator.py`의 `build_simulation_result(...)` 호출에 한 줄을 더한다. `savings_portfolio_result=savings_portfolio_result,` 바로 다음이다:

```python
        savings_portfolio_result=savings_portfolio_result,
        savings_policy_validation=savings_validation,
```

`savings_validation`은 이미 `run_simulation`의 인자이자 지역변수다(정의 294행, 대입 332-333행). 새로 만들지 않는다.

- [ ] **Step 6: 테스트를 통과시킨다**

Run: `python -m pytest tests/schemas/test_simulation_result_contract.py -v`
Expected: PASS (새 테스트 2개 포함)

- [ ] **Step 7: 전체 테스트와 린트**

Run: `python -m pytest -q && python -m ruff check app/services/simulation_result.py app/services/simulation_orchestrator.py tests/schemas/test_simulation_result_contract.py`
Expected: 전부 통과. 실패가 있으면 `section_schema_version`을 문자열로 박아둔 다른 테스트일 수 있다 — 그 경우 기대값을 `1.1.0`으로 고친다.

- [ ] **Step 8: 커밋**

```bash
git add app/services/simulation_result.py app/services/simulation_orchestrator.py tests/schemas/test_simulation_result_contract.py
git commit -m "feat: 저축 절에 최종 정책 재검증 판정을 싣는다

대시보드가 final_policy_status·validation_reasons를 쓰는데 조립 단계에서
버려지고 있었다. 값은 SavingsPortfolioOutcome.validation에 이미 있다.

검증이 없으면 키를 넣지 않는다 — 판정을 받지 못한 상태는 통과가 아니다."
```

---

### Task 2: core — PDF 렌더러 환경 구축

`weasyprint`는 선택 의존성이고 이 맥에 없다. 한글 글꼴도 없다. 설치하고, 설치 여부를 코드로 확인할 수 있게 만든다.

**Files:**
- Create: `tests/reports/test_pdf_environment.py`
- 설치: 시스템 패키지와 Python 패키지 (커밋 대상 아님)

**Interfaces:**
- Consumes: `pdf_rendering_available()`, `render_pdf()`, `verify_korean_glyphs()`, `embedded_font_names()` — 전부 `app/reports/pdf.py`
- Produces: 없음. 이 과제는 환경과 그 환경을 확인하는 테스트만 남긴다.

- [ ] **Step 1: 한글 글꼴을 설치한다**

```bash
brew install --cask font-noto-sans-cjk
```

`~/Library/Fonts`에 이미 있는 `NotoSansKR-*.ttf`로는 **안 된다.** `app/reports/pdf.py:187-192`의 검사는 폰트 이름에 `cjk`·`malgun`·`nanum`·`gothic`·`batang`·`gulim`·`dotum` 중 하나를 요구하고, `app/reports/templates/official.py:45-46`의 CSS는 `"Noto Sans CJK KR"`을 지명한다. `"Noto Sans KR"`은 다른 폰트다.

- [ ] **Step 2: weasyprint를 설치한다**

```bash
python -m pip install -e ".[pdf]"
```

pango·cairo·libffi는 이미 설치돼 있다. gdk-pixbuf는 weasyprint 53+가 요구하지 않는다.

- [ ] **Step 3: 실패하는 테스트를 쓴다**

`tests/reports/test_pdf_environment.py`를 새로 만든다:

```python
"""PDF 경로가 실제로 동작하는지 확인한다.

PDF 생성은 글꼴이 없어도 **성공한다.** 글자만 빈 상자가 될 뿐이라 크기·형식
검사로는 잡히지 않는다. 그래서 렌더 가능 여부와 한글 글꼴 임베드를 따로 본다.

``weasyprint``는 선택 의존성(`pyproject.toml`의 `[pdf]`)이라 없는 환경도
정상이다. 그럴 때는 건너뛴다 — 없는 것을 실패로 보고하면 기본 의존성만
설치한 개발자의 전체 테스트가 빨간색이 된다.
"""

import pytest

from app.reports.pdf import (
    embedded_font_names,
    pdf_rendering_available,
    render_pdf,
    verify_korean_glyphs,
)

pytestmark = pytest.mark.skipif(
    not pdf_rendering_available(),
    reason="weasyprint가 설치되지 않았습니다. python -m pip install -e '.[pdf]'",
)

_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
body { font-family: "Noto Serif CJK KR", "Noto Sans CJK KR", serif; }
</style></head>
<body><h1>주택금융 보고서</h1><p>필요 자기자본 1억 2,000만원</p></body></html>"""


def test_rendered_pdf_is_a_pdf() -> None:
    rendered = render_pdf(_HTML)

    assert rendered.content.startswith(b"%PDF-")
    assert rendered.byte_size > 0


def test_rendered_pdf_embeds_a_korean_capable_font() -> None:
    """한글이 두부로 나가지 않는지 본다. 이 검사가 실패하면 글꼴 미설치다."""
    rendered = render_pdf(_HTML)

    verify_korean_glyphs(rendered.content)
    assert embedded_font_names(rendered.content)
```

- [ ] **Step 4: 테스트를 돌린다**

Run: `python -m pytest tests/reports/test_pdf_environment.py -v`
Expected: PASS 2건. `skipped`가 나오면 Step 2가 실패한 것이고, `verify_korean_glyphs`에서 실패하면 Step 1이 실패한 것이다. 어느 쪽이든 넘어가지 말고 해결한다.

- [ ] **Step 5: 보관 설정을 `.env`에 넣는다**

`.env`에 다음 한 줄을 추가한다. **파일의 다른 내용을 읽거나 출력하지 않는다.**

```
REPORT_ARCHIVE_PROVIDER=filesystem
```

`.env`는 gitignore 대상이다. 커밋하지 않는다.

- [ ] **Step 6: 엔드포인트를 손으로 확인한다**

서버를 띄우고(`uvicorn app.main:app --reload`) SSH 터널이 열려 있는 상태에서, 페르소나 하나에 해당하는 `SimulationInput`으로 호출한다:

```bash
curl -s -D /tmp/hdr.txt -o /tmp/report.pdf \
  -X POST 'http://127.0.0.1:8000/api/v1/reports?format=pdf' \
  -H 'content-type: application/json' \
  -d '{"profile":{"age":24,"annual_income":24000000},
       "housing_goal":{"target_price":325000000,"target_date":"2028-07-01","region_code":"11650"},
       "financial_snapshot":{"monthly_income":2000000,"monthly_expense":1200000,"liquid_assets":8000000},
       "loan_request":{"months":360,"housing_status":"NO_HOUSE","monthly_essential_expense":1200000}}'
head -c 5 /tmp/report.pdf; grep -i 'x-report-id\|content-disposition' /tmp/hdr.txt
```

Expected: `%PDF-`가 찍히고, 헤더에 `inline`과 `X-Report-Id`가 보인다.

503이 나면 원인은 셋 중 하나다 — 글꼴 미설치, DB 미연결(SSH 터널), 저장 경로 권한. 501이면 Step 5가 반영되지 않은 것이다.

- [ ] **Step 7: 커밋**

```bash
git add tests/reports/test_pdf_environment.py
git commit -m "test: PDF 렌더러와 한글 글꼴 가용성을 코드로 확인한다

PDF는 글꼴이 없어도 생성에 성공하고 글자만 빈 상자가 된다. 크기·형식
검사로는 절대 잡히지 않아 글꼴 임베드를 따로 본다.

weasyprint는 선택 의존성이라 없으면 건너뛴다."
```

---

### Task 3: web — Step 1 폼 스키마 확장

네 필드를 추가하고 `current_assets`를 필수로 올린다. UI는 다음 과제에서 붙인다.

**Files:**
- Modify: `housing-finance-web/src/features/input/form-schema.ts`
- Test: `housing-finance-web/src/features/input/form-schema.test.ts`

**Interfaces:**
- Produces:
  - `InputFormValues`에 `months: number`, `housing_status: string`, `monthly_essential_expense: number`, `exclusive_area_m2: number`가 생기고 `current_assets: number`가 필수가 된다.
  - `export const HOUSING_STATUS_OPTIONS: readonly string[]` — `["NO_HOUSE", "FIRST_HOME_BUYER", "ONE_HOUSE_DISPOSAL_PLEDGED", "ONE_HOUSE_KEEPING", "MULTI_HOUSE"]`
  - `export const LOAN_TERM_OPTIONS: readonly number[]` — `[120, 240, 360, 480]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`src/features/input/form-schema.test.ts` 맨 아래에 추가한다. 이 파일은 이미 `SAMPLE = "persona_e_college_student_basic"`(7행)과 `loadProfile`·`inputFormSchema`·`toFormValues` import를 갖고 있다. 그대로 쓴다.

```ts
const VALID_FORM_VALUES = {
  age: 24,
  household_size: 1,
  monthly_income: 2000000,
  monthly_average_expense: 1200000,
  current_assets: 8000000,
  target_region: "11650",
  target_price: 325000000,
  target_move_in_ym: "2028-07",
  risk_preference: "stability",
  monthly_savings_budget: 500000,
  lump_sum_budget: 0,
  emergency_reserve: 1000000,
  months: 360,
  housing_status: "NO_HOUSE",
  monthly_essential_expense: 1200000,
  exclusive_area_m2: 84,
};

describe("대출 조건 필드", () => {
  it("기본값은 만기 360개월·무주택·전용면적 84이다", async () => {
    const values = toFormValues(await loadProfile(SAMPLE));

    expect(values.months).toBe(360);
    expect(values.housing_status).toBe("NO_HOUSE");
    expect(values.exclusive_area_m2).toBe(84);
  });

  it("필수생활비 기본값은 월평균지출과 같다", async () => {
    // 비율을 도입하면 근거 없는 숫자가 계산에 들어가고, 그 방향이 한도를
    // 키운다. 지출 전액을 필수로 보는 것이 지어내지 않으면서 보수적이다.
    const profile = await loadProfile(SAMPLE);
    const values = toFormValues(profile);

    expect(values.monthly_essential_expense).toBe(
      profile.finance.monthly_average_expense,
    );
  });

  it("주택보유상태 기본값을 생애최초로 두지 않는다", async () => {
    // 생애최초는 LTV 70%, 무주택은 40%. 아무것도 고르지 않은 사용자가
    // 가장 유리한 한도를 받아서는 안 된다.
    const values = toFormValues(await loadProfile(SAMPLE));

    expect(values.housing_status).not.toBe("FIRST_HOME_BUYER");
  });

  it("보유자산을 비우면 검증에 실패한다", () => {
    const result = inputFormSchema.safeParse({
      ...VALID_FORM_VALUES,
      current_assets: "",
    });

    expect(result.success).toBe(false);
  });

  it("전용면적 0은 거부한다", () => {
    const result = inputFormSchema.safeParse({
      ...VALID_FORM_VALUES,
      exclusive_area_m2: 0,
    });

    expect(result.success).toBe(false);
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test -- form-schema`
Expected: FAIL — `values.months`가 `undefined`

- [ ] **Step 3: 스키마를 고친다**

`src/features/input/form-schema.ts`:

```ts
/** LTV 비율을 가르는 차주 구분. core의 `HousingStatus`(6·27 방안)와 같은 값이다. */
export const HOUSING_STATUS_OPTIONS = [
  "NO_HOUSE",
  "FIRST_HOME_BUYER",
  "ONE_HOUSE_DISPOSAL_PLEDGED",
  "ONE_HOUSE_KEEPING",
  "MULTI_HOUSE",
] as const;

/** 주택담보대출 만기(개월). 10·20·30·40년. */
export const LOAN_TERM_OPTIONS = [120, 240, 360, 480] as const;
```

`inputFormSchema`에서 `current_assets`를 필수로 바꾸고 네 필드를 더한다:

```ts
  current_assets: won,
  ...
  months: z.coerce
    .number()
    .int()
    .refine((value) => LOAN_TERM_OPTIONS.includes(value as 120), "만기를 선택하세요"),
  housing_status: z
    .string()
    .refine(
      (value) => HOUSING_STATUS_OPTIONS.includes(value as "NO_HOUSE"),
      "주택 보유 상태를 선택하세요",
    ),
  monthly_essential_expense: won,
  exclusive_area_m2: z.preprocess(
    (value) => (value === "" ? undefined : value),
    z.coerce.number({ error: "전용면적을 입력하세요" }).gt(0, "0보다 커야 합니다"),
  ),
```

`toFormValues`에 네 줄을 더한다:

```ts
    // 만기는 사용자가 고르는 값이다. 30년이 주택담보대출 표준.
    months: 360,
    // 생애최초(LTV 70%)를 기본값으로 두지 않는다. 무주택(40%)에서 시작해
    // 사용자가 직접 주장하게 한다 — 모르는 값을 유리한 쪽에 두지 않는다.
    housing_status: "NO_HOUSE",
    // 지출 전액을 필수로 본다. 비율을 도입하면 근거 없는 숫자가 계산에
    // 들어가고, 필수생활비가 작을수록 Buffer가 작아져 한도가 커진다.
    monthly_essential_expense: profile.finance.monthly_average_expense,
    // 목표가가 전용 85㎡ 이하 실거래에서 나온 값이다.
    exclusive_area_m2: 84,
```

- [ ] **Step 4: 테스트를 통과시킨다**

Run: `npm test -- form-schema && npx tsc --noEmit`
Expected: PASS. 타입 오류가 나면 `InputFormValues`를 쓰는 다른 파일이 새 필드를 몰라서다 — 다음 과제에서 UI를 붙이므로 여기서는 타입만 맞춘다.

- [ ] **Step 5: 전체 테스트**

Run: `npm test`
Expected: PASS. `input-wizard.test.tsx`나 `step-review.test.tsx`가 폼 값 객체를 직접 만들고 있으면 새 필드 네 개를 더해 준다.

- [ ] **Step 6: 커밋**

```bash
git add src/features/input/form-schema.ts src/features/input/form-schema.test.ts
git commit -m "feat: Step 1 폼에 대출 조건 네 필드를 추가한다

만기·주택보유상태·필수생활비가 없으면 loan_request를 만들 수 없어 보고서의
대출 절이 통째로 NOT_RUN이 된다. 전용면적은 acquisition_costs를 채워
전략비교 절을 연다.

기본값은 전부 '모르면 한도가 커지는 쪽'의 반대로 뒀다. current_assets는
liquid_assets가 필수라 optional로 둘 수 없다 — 비어 있으면 0으로 채우고
싶은 압력이 생긴다."
```

---

### Task 4: web — 대출 조건 UI와 입력 확인 화면

**Files:**
- Create: `housing-finance-web/src/features/input/loan-fields.tsx`
- Modify: `housing-finance-web/src/features/input/desired-home-panel.tsx`
- Modify: `housing-finance-web/src/features/input/step-input.tsx`
- Modify: `housing-finance-web/src/features/input/step-review.tsx`
- Modify: `housing-finance-web/src/lib/format/codes.ts`
- Test: `housing-finance-web/src/features/input/loan-fields.test.tsx` (신규), `step-review.test.tsx` (수정)

**Interfaces:**
- Consumes: `HOUSING_STATUS_OPTIONS`, `LOAN_TERM_OPTIONS`, `InputFormValues` (Task 3)
- Produces: `export function LoanFields(): JSX.Element` · `housingStatusLabel(code: string): string` · `loanTermLabel(months: number): string`

- [ ] **Step 1: 라벨 함수의 실패하는 테스트를 쓴다**

`src/lib/format/codes.test.ts`에 추가한다:

```ts
describe("housingStatusLabel", () => {
  it("다섯 구분을 한국어로 옮긴다", () => {
    expect(housingStatusLabel("NO_HOUSE")).toBe("무주택");
    expect(housingStatusLabel("FIRST_HOME_BUYER")).toBe("생애최초 주택구입");
    expect(housingStatusLabel("ONE_HOUSE_DISPOSAL_PLEDGED")).toBe("1주택 처분조건부");
    expect(housingStatusLabel("ONE_HOUSE_KEEPING")).toBe("1주택 미처분 추가구입");
    expect(housingStatusLabel("MULTI_HOUSE")).toBe("2주택 이상");
  });

  it("모르는 코드는 코드 그대로 보여준다", () => {
    // 임의로 뭉개면 화면이 사실과 달라진다.
    expect(housingStatusLabel("SOMETHING_ELSE")).toBe("SOMETHING_ELSE");
  });
});

describe("loanTermLabel", () => {
  it("개월을 연 단위로 보여준다", () => {
    expect(loanTermLabel(360)).toBe("30년 (360개월)");
    expect(loanTermLabel(120)).toBe("10년 (120개월)");
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test -- codes`
Expected: FAIL — `housingStatusLabel is not a function`

- [ ] **Step 3: 라벨 함수를 만든다**

`src/lib/format/codes.ts`에 추가한다. 파일에 이미 있는 다른 `*Label` 함수의 형태를 그대로 따른다:

```ts
const HOUSING_STATUS_LABELS: Record<string, string> = {
  NO_HOUSE: "무주택",
  FIRST_HOME_BUYER: "생애최초 주택구입",
  ONE_HOUSE_DISPOSAL_PLEDGED: "1주택 처분조건부",
  ONE_HOUSE_KEEPING: "1주택 미처분 추가구입",
  MULTI_HOUSE: "2주택 이상",
};

export function housingStatusLabel(code: string): string {
  return HOUSING_STATUS_LABELS[code] ?? code;
}

export function loanTermLabel(months: number): string {
  return `${months / 12}년 (${months}개월)`;
}
```

- [ ] **Step 4: 라벨 테스트를 통과시킨다**

Run: `npm test -- codes`
Expected: PASS

- [ ] **Step 5: `LoanFields`의 실패하는 테스트를 쓴다**

`src/features/input/loan-fields.test.tsx`를 새로 만든다. 이 저장소의 다른 폼 테스트(`desired-home-panel.test.tsx`)가 `FormProvider`를 감싸는 방식을 그대로 따른다:

```tsx
import { render, screen } from "@testing-library/react";
import { FormProvider, useForm } from "react-hook-form";
import { describe, expect, it } from "vitest";

import type { InputFormValues } from "./form-schema";
import { LoanFields } from "./loan-fields";

function Harness({ defaults }: { defaults: Partial<InputFormValues> }) {
  const form = useForm<InputFormValues>({
    defaultValues: {
      months: 360,
      housing_status: "NO_HOUSE",
      monthly_essential_expense: 1200000,
      ...defaults,
    } as InputFormValues,
  });
  return (
    <FormProvider {...form}>
      <LoanFields />
    </FormProvider>
  );
}

describe("LoanFields", () => {
  it("만기 네 가지를 연 단위로 보여준다", () => {
    render(<Harness defaults={{}} />);

    expect(screen.getByRole("option", { name: "30년 (360개월)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "10년 (120개월)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "40년 (480개월)" })).toBeInTheDocument();
  });

  it("주택 보유 상태 다섯 가지를 한국어로 보여준다", () => {
    render(<Harness defaults={{}} />);

    expect(screen.getByRole("option", { name: "무주택" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "생애최초 주택구입" })).toBeInTheDocument();
  });

  it("생애최초를 고르면 한도가 커진다는 것을 알린다", () => {
    render(<Harness defaults={{ housing_status: "FIRST_HOME_BUYER" }} />);

    expect(screen.getByText(/LTV/)).toBeInTheDocument();
  });

  it("필수생활비가 무엇인지 설명한다", () => {
    render(<Harness defaults={{}} />);

    expect(screen.getByText(/총지출이 아니라/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: 실패를 확인한다**

Run: `npm test -- loan-fields`
Expected: FAIL — `Failed to resolve import "./loan-fields"`

- [ ] **Step 7: `LoanFields`를 만든다**

`src/features/input/loan-fields.tsx`:

```tsx
"use client";

import { useFormContext } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { housingStatusLabel, loanTermLabel } from "@/lib/format/codes";
import { koreanUnitHint } from "@/lib/format/money";

import { FieldRow } from "./field-row";
import {
  HOUSING_STATUS_OPTIONS,
  LOAN_TERM_OPTIONS,
  type InputFormValues,
} from "./form-schema";

const SELECT_CLASS =
  "h-9 rounded-md border border-line bg-surface px-3 text-sm";

export function LoanFields() {
  const {
    register,
    watch,
    formState: { errors },
  } = useFormContext<InputFormValues>();

  const housingStatus = watch("housing_status");

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <FieldRow label="만기" htmlFor="months" error={errors.months?.message}>
        <select id="months" className={SELECT_CLASS} {...register("months")}>
          {LOAN_TERM_OPTIONS.map((months) => (
            <option key={months} value={months}>
              {loanTermLabel(months)}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow
        label="주택 보유 상태"
        htmlFor="housing_status"
        hint={
          housingStatus === "FIRST_HOME_BUYER"
            ? "생애최초는 LTV 70%가 적용됩니다. 무주택(40%)보다 한도가 큽니다."
            : undefined
        }
        error={errors.housing_status?.message}
      >
        <select
          id="housing_status"
          className={SELECT_CLASS}
          {...register("housing_status")}
        >
          {HOUSING_STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {housingStatusLabel(status)}
            </option>
          ))}
        </select>
      </FieldRow>

      <FieldRow
        label="필수 생활비 (원)"
        htmlFor="monthly_essential_expense"
        hint={
          koreanUnitHint(watch("monthly_essential_expense")) +
          " · 총지출이 아니라 줄일 수 없는 생활비입니다. 기본값은 월평균지출 전액입니다."
        }
        error={errors.monthly_essential_expense?.message}
      >
        <Input
          id="monthly_essential_expense"
          type="number"
          {...register("monthly_essential_expense")}
        />
      </FieldRow>
    </div>
  );
}
```

- [ ] **Step 8: 테스트를 통과시킨다**

Run: `npm test -- loan-fields`
Expected: PASS 4건

- [ ] **Step 9: `StepInput`에 배치한다**

`src/features/input/step-input.tsx`에서 `import { LoanFields } from "./loan-fields";`를 더하고, "저축 계획" `<Group>` **앞에** 넣는다:

```tsx
      <Group
        title="대출 조건"
        description="이 세 값이 없으면 보고서의 대출 관련 절이 계산되지 않습니다."
      >
        <LoanFields />
      </Group>
```

- [ ] **Step 10: 전용면적을 희망 주택 패널에 넣는다**

`src/features/input/desired-home-panel.tsx`에 `FieldRow` 하나를 더한다. 파일에 이미 있는 `FieldRow` 사용 형태를 그대로 따른다:

```tsx
      <FieldRow
        label="전용면적 (㎡)"
        htmlFor="exclusive_area_m2"
        hint="취득세를 확정하는 데 씁니다. 85㎡ 이하면 농어촌특별세가 붙지 않습니다."
        error={errors.exclusive_area_m2?.message}
      >
        <Input
          id="exclusive_area_m2"
          type="number"
          step="0.01"
          {...register("exclusive_area_m2")}
        />
      </FieldRow>
```

- [ ] **Step 11: 입력 확인 화면에 네 값을 표시한다**

`src/features/input/step-review.tsx`는 `const values = watch();`로 폼 값을 읽고 `ReadonlyRow`로 그린다. 금액에는 `formatWon`을 쓴다(`formatKoreanUnit`이 아니다).

**(a)** 왼쪽 열의 `current_assets` 조건부 렌더를 없앤다. Task 3에서 필수가 됐으므로 `undefined`일 수 없고, 조건을 남겨 두면 "값이 없을 수도 있다"는 잘못된 신호가 남는다:

```tsx
            <ReadonlyRow
              label="보유 자산"
              value={formatWon(values.current_assets)}
            />
```

**(b)** 오른쪽 열의 `비상 예비금` 줄 **바로 다음**에 네 줄을 더한다:

```tsx
            <ReadonlyRow label="만기" value={loanTermLabel(values.months)} />
            <ReadonlyRow
              label="주택 보유 상태"
              value={housingStatusLabel(values.housing_status)}
            />
            <ReadonlyRow
              label="필수 생활비"
              value={formatWon(values.monthly_essential_expense)}
            />
            <ReadonlyRow
              label="전용면적"
              value={`${values.exclusive_area_m2}㎡`}
            />
```

**(c)** import를 넓힌다:

```tsx
import { housingStatusLabel, loanTermLabel, riskPreferenceLabel } from "@/lib/format/codes";
```

- [ ] **Step 12: 확인 화면 테스트를 더한다**

`src/features/input/step-review.test.tsx`는 `Harness` 컴포넌트로 렌더한다(`profile`·`mydata`·`mydataLoaded`·`overrides`를 받는다). 그 형태를 그대로 쓴다:

```tsx
it("대출 조건 네 값을 모두 보여준다", async () => {
  const [profile, mydata] = await Promise.all([
    loadProfile(SAMPLE),
    loadMydata(SAMPLE),
  ]);
  render(<Harness profile={profile} mydata={mydata} mydataLoaded={false} />);

  expect(screen.getByText("30년 (360개월)")).toBeInTheDocument();
  expect(screen.getByText("무주택")).toBeInTheDocument();
  expect(screen.getByText("84㎡")).toBeInTheDocument();
  expect(
    screen.getByText(formatWon(profile.finance.monthly_average_expense)),
  ).toBeInTheDocument();
});
```

- [ ] **Step 13: 전체 테스트와 타입 검사**

Run: `npm test && npx tsc --noEmit`
Expected: 전부 PASS

- [ ] **Step 14: 커밋**

```bash
git add src/features/input/ src/lib/format/codes.ts src/lib/format/codes.test.ts
git commit -m "feat: 대출 조건 입력과 전용면적을 Step 1에 붙인다

전용면적은 대출 조건이 아니라 목표 주택의 사실이므로 희망 주택 패널에 둔다.

생애최초를 고르면 LTV가 70%로 열린다는 것을 그 자리에서 알린다. 필수생활비
입력에는 총지출과 다르다는 설명을 붙인다 — 총지출을 적으면 한도가 실제보다
작게, 너무 낮게 적으면 크게 나온다."
```

---

### Task 5: web — 폼값 → `SimulationInput` 매핑

**Files:**
- Create: `housing-finance-web/src/lib/api/simulation-input.ts`
- Test: `housing-finance-web/src/lib/api/simulation-input.test.ts`

**Interfaces:**
- Consumes: `InputFormValues` (Task 3), `PersonaProfile` (`@/lib/contracts/persona`)
- Produces:
  - `export type SimulationInputPayload`
  - `export function buildSimulationInput(values: InputFormValues, profile: PersonaProfile): SimulationInputPayload`
  - `export const FIXED_ACQUISITION_ASSUMPTIONS: readonly string[]` — 화면에 표시할 가정 문구

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`src/lib/api/simulation-input.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { toFormValues } from "@/features/input/form-schema";
import { loadProfile } from "@/lib/fixtures/loader";

import { buildSimulationInput } from "./simulation-input";

const PERSONA = "persona_e_college_student_basic";

async function build(overrides: Record<string, unknown> = {}) {
  const profile = await loadProfile(PERSONA);
  return buildSimulationInput(
    { ...toFormValues(profile), ...overrides } as never,
    profile,
  );
}

describe("buildSimulationInput", () => {
  it("목표 시점 YYYY-MM을 그 달 1일로 옮긴다", async () => {
    const input = await build({ target_move_in_ym: "2028-07" });

    expect(input.housing_goal.target_date).toBe("2028-07-01");
  });

  it("연소득은 폼이 아니라 프로필의 검증된 값에서 온다", async () => {
    const profile = await loadProfile(PERSONA);
    const input = await build();

    expect(input.profile.annual_income).toBe(
      profile.finance.annual_income_verified,
    );
  });

  it("생애최초를 고를 때만 is_first_home_buyer가 참이다", async () => {
    expect((await build({ housing_status: "NO_HOUSE" })).profile.is_first_home_buyer).toBe(false);
    expect(
      (await build({ housing_status: "FIRST_HOME_BUYER" })).profile.is_first_home_buyer,
    ).toBe(true);
  });

  it("취득 후 보유주택수를 주택보유상태에서 유도한다", async () => {
    const noHouse = await build({ housing_status: "NO_HOUSE" });
    const keeping = await build({ housing_status: "ONE_HOUSE_KEEPING" });

    expect(noHouse.acquisition_costs.household_home_count_after_purchase).toBe(1);
    expect(keeping.acquisition_costs.household_home_count_after_purchase).toBe(2);
  });

  it("다주택은 취득 후 주택수를 확정하지 않는다", async () => {
    // 2주택 이상은 '2채'가 아니라 '2채 이상'이라는 뜻이다. 3을 적으면
    // 4주택 차주를 통과시키고, 그것은 세액을 작게 잡는 방향이다.
    const input = await build({ housing_status: "MULTI_HOUSE" });

    expect(
      input.acquisition_costs.household_home_count_after_purchase,
    ).toBeUndefined();
  });

  it("대출 요청 세 값을 폼에서 그대로 가져온다", async () => {
    const input = await build({
      months: 240,
      monthly_essential_expense: 900000,
    });

    expect(input.loan_request.months).toBe(240);
    expect(input.loan_request.housing_status).toBe("NO_HOUSE");
    expect(input.loan_request.monthly_essential_expense).toBe(900000);
  });

  it("유동자산은 폼의 보유자산이며 0으로 대체하지 않는다", async () => {
    const input = await build({ current_assets: 8000000 });

    expect(input.financial_snapshot.liquid_assets).toBe(8000000);
  });

  it("고급주택 아님을 가정으로 명시한다", async () => {
    const input = await build();

    expect(input.acquisition_costs.is_luxury_home).toBe(false);
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test -- simulation-input`
Expected: FAIL — `Failed to resolve import "./simulation-input"`

- [ ] **Step 3: 매핑을 구현한다**

`src/lib/api/simulation-input.ts`:

```ts
import type { InputFormValues } from "@/features/input/form-schema";
import type { PersonaProfile } from "@/lib/contracts/persona";

/**
 * `POST /api/v1/simulations`와 `POST /api/v1/reports`가 받는 본문.
 *
 * core의 `app/schemas/simulation.py`가 정하는 모양이다. 이 파일 밖에서는
 * 이 모양을 알지 못한다 — 경계를 한 곳에 가둔다.
 */
export type SimulationInputPayload = {
  profile: {
    age: number;
    household_size: number;
    annual_income: number;
    employment_type: string | null;
    is_first_home_buyer: boolean;
    is_married: boolean;
  };
  housing_goal: {
    goal_type: "HOME_PURCHASE";
    target_price: number;
    target_date: string;
    region_code: string;
  };
  financial_snapshot: {
    monthly_income: number;
    monthly_expense: number;
    liquid_assets: number;
    monthly_debt_payment: number;
    emergency_reserve: number;
  };
  loan_request: {
    months: number;
    housing_status: string;
    monthly_essential_expense: number;
  };
  savings_request: {
    fund_needed_date: string;
    monthly_savings_budget: number;
    lump_sum_budget: number;
    liquidity_preference: string;
    accepts_principal_risk: boolean;
    maximum_recommended_products: number;
  };
  acquisition_costs: {
    buyer_is_corporation: boolean;
    is_registered_housing: boolean;
    is_luxury_home: boolean;
    exclusive_area_m2: number;
    household_home_count_after_purchase?: number;
  };
};

/**
 * 이 서비스 범위에서 고정한 취득 사실. **화면에 가정임을 표시한다.**
 *
 * 목표가를 사용자가 직접 바꿀 수 있으므로 조용히 두지 않는다.
 */
export const FIXED_ACQUISITION_ASSUMPTIONS = [
  "매수자는 개인이며 법인이 아닌 것으로 계산했습니다.",
  "취득 대상은 주택으로 계산했습니다.",
  "고급주택이 아닌 것으로 계산했습니다. 고급주택이면 취득세가 중과되어 실제 비용은 더 큽니다.",
] as const;

/** `YYYY-MM` → `YYYY-MM-01`. 계약은 날짜를 요구하고 폼은 월까지만 받는다. */
function firstOfMonth(ym: string): string {
  return `${ym}-01`;
}

/** `YYYYMMDD` → `YYYY-MM-DD`. 프로필의 `fund_needed_date` 형식이다. */
function isoFromYmd(ymd: string): string {
  return `${ymd.slice(0, 4)}-${ymd.slice(4, 6)}-${ymd.slice(6, 8)}`;
}

/**
 * 취득 후 보유주택수.
 *
 * `MULTI_HOUSE`는 채우지 않는다. 2주택 이상은 '2채'가 아니라 '2채 이상'이라는
 * 뜻이어서 숫자를 적으면 더 많이 가진 차주를 통과시키고, 그것은 세액을 작게
 * 잡는 방향이다. 같은 이유로 core의 `_user_facts()`도 이 경우를 비운다.
 */
function homeCountAfterPurchase(status: string): number | undefined {
  if (status === "NO_HOUSE" || status === "FIRST_HOME_BUYER") return 1;
  if (status === "ONE_HOUSE_DISPOSAL_PLEDGED" || status === "ONE_HOUSE_KEEPING") return 2;
  return undefined;
}

export function buildSimulationInput(
  values: InputFormValues,
  profile: PersonaProfile,
): SimulationInputPayload {
  const homeCount = homeCountAfterPurchase(values.housing_status);

  return {
    profile: {
      age: values.age,
      household_size: values.household_size,
      // 연소득은 폼에 없다. 검증된 값을 쓰고 월소득 × 12로 지어내지 않는다.
      annual_income: profile.finance.annual_income_verified,
      employment_type: profile.basic.employment_type,
      is_first_home_buyer: values.housing_status === "FIRST_HOME_BUYER",
      is_married: profile.basic.marital_status === "married",
    },
    housing_goal: {
      goal_type: "HOME_PURCHASE",
      target_price: values.target_price,
      target_date: firstOfMonth(values.target_move_in_ym),
      region_code: values.target_region,
    },
    financial_snapshot: {
      monthly_income: values.monthly_income,
      monthly_expense: values.monthly_average_expense,
      liquid_assets: values.current_assets,
      monthly_debt_payment: profile.finance.monthly_debt_payment ?? 0,
      emergency_reserve: values.emergency_reserve,
    },
    loan_request: {
      months: values.months,
      housing_status: values.housing_status,
      monthly_essential_expense: values.monthly_essential_expense,
    },
    savings_request: {
      fund_needed_date: isoFromYmd(profile.savings.fund_needed_date),
      monthly_savings_budget: values.monthly_savings_budget,
      lump_sum_budget: values.lump_sum_budget,
      liquidity_preference: profile.savings.liquidity_preference,
      accepts_principal_risk: profile.savings.accepts_principal_risk,
      maximum_recommended_products: profile.savings.maximum_recommended_products,
    },
    acquisition_costs: {
      buyer_is_corporation: false,
      is_registered_housing: true,
      is_luxury_home: false,
      exclusive_area_m2: values.exclusive_area_m2,
      ...(homeCount === undefined
        ? {}
        : { household_home_count_after_purchase: homeCount }),
    },
  };
}
```

`monthly_debt_payment`에 `?? 0`을 쓰는 것은 안전하다 — 부채 상환액이 클수록 한도가 작아지므로 0은 보수적인 방향이 아니라 **관대한** 방향처럼 보이지만, 이 값은 프로필에 있으면 있고 없으면 실제로 부채가 없다는 뜻이다(픽스처 20명 중 부채가 있는 페르소나에만 이 키가 있다). 다른 필드에 `?? 0`을 추가하지 말 것.

- [ ] **Step 4: 테스트를 통과시킨다**

Run: `npm test -- simulation-input && npx tsc --noEmit`
Expected: PASS 8건

- [ ] **Step 5: 커밋**

```bash
git add src/lib/api/simulation-input.ts src/lib/api/simulation-input.test.ts
git commit -m "feat: 폼값을 SimulationInput으로 옮기는 경계를 만든다

SimulationInput의 모양을 아는 파일을 하나로 가둔다.

다주택일 때 취득 후 보유주택수를 채우지 않는다 — '2채 이상'을 2로 적으면
3채 차주를 통과시키고 세액을 작게 잡는다. core의 _user_facts()가 같은
이유로 owned_house_count를 비우는 것과 같다.

고정값 셋(법인 아님·주택 맞음·고급주택 아님)은 가정 문구로 함께 내보내
화면이 조용히 넘어가지 않게 한다."
```

---

### Task 6: web — 백엔드 클라이언트와 결과 매핑

**Files:**
- Create: `housing-finance-web/src/lib/api/errors.ts`
- Create: `housing-finance-web/src/lib/api/client.ts`
- Create: `housing-finance-web/src/lib/api/portfolio-result.ts`
- Modify: `housing-finance-web/src/lib/contracts/result.ts`
- Modify: `housing-finance-web/src/features/dashboard/portfolio-status-notice.tsx`
- Test: `src/lib/api/portfolio-result.test.ts`, `src/lib/api/client.test.ts` (신규)

**Interfaces:**
- Consumes: `SimulationInputPayload` (Task 5), `PortfolioResult`·`portfolioResultSchema` (`@/lib/contracts/result`)
- Produces:
  - `export class ApiError extends Error { readonly status: number; readonly detail: string }`
  - `export function apiErrorMessage(error: unknown): string`
  - `export async function postSimulation(input: SimulationInputPayload): Promise<unknown>`
  - `export async function postReportPdf(input: SimulationInputPayload): Promise<string>` — `X-Report-Id`를 돌려준다
  - `export function toPortfolioResult(simulation: unknown, profile: PersonaProfile, values: InputFormValues): PortfolioResult`

- [ ] **Step 1: `evaluation`을 optional로 내리는 테스트를 쓴다**

`SimulationResult`에는 상품 자격판정 집계(`ELIGIBLE`/`INELIGIBLE`)가 없다. 배치 파이프라인의 산출물이라 실시간 경로에는 존재하지 않는다. 0으로 채우지 않고 없는 상태로 둔다.

`src/lib/contracts/result.test.ts`가 있으면 거기에, 없으면 `src/lib/api/portfolio-result.test.ts`에 넣는다:

```ts
it("evaluation이 없어도 계약을 통과한다", async () => {
  const base = await loadResult("persona_e_college_student_basic");
  const { evaluation: _drop, ...withoutEvaluation } = base;

  expect(portfolioResultSchema.safeParse(withoutEvaluation).success).toBe(true);
});
```

- [ ] **Step 2: 결과 매핑의 실패하는 테스트를 쓴다**

`src/lib/api/portfolio-result.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { toFormValues } from "@/features/input/form-schema";
import { loadProfile } from "@/lib/fixtures/loader";

import { toPortfolioResult } from "./portfolio-result";

const PERSONA = "persona_e_college_student_basic";

const SIMULATION = {
  as_of: "2026-08-02",
  savings_portfolio: {
    run_status: "COMPLETED",
    section_schema_version: "savings-portfolio@1.1.0",
    engine_status: "COMPLETE",
    result: {
      status: "COMPLETE",
      coverage_ratio: "1",
      monthly_allocated: "500000",
      monthly_unallocated: "0",
      lump_sum_allocated: "0",
      lump_sum_unallocated: "0",
      expected_total_principal: "12000000",
      expected_maturity_amount: "12300000",
      expected_net_interest: "300000",
      allocations: [],
      reasons: [],
      final_policy_status: "PASS",
      final_policy_valid: true,
      validation_reasons: ["상품 X가 재검증에서 제외됨"],
    },
    missing_inputs: [],
    reasons: [],
    assumptions: [],
    policy_sources: [],
  },
};

async function map(simulation: unknown = SIMULATION) {
  const profile = await loadProfile(PERSONA);
  return toPortfolioResult(simulation, profile, toFormValues(profile));
}

describe("toPortfolioResult", () => {
  it("정책 판정을 그대로 옮긴다", async () => {
    const result = await map();

    expect(result.final_policy_status).toBe("PASS");
    expect(result.final_policy_valid).toBe(true);
    expect(result.validation_reasons).toEqual(["상품 X가 재검증에서 제외됨"]);
  });

  it("정책 판정이 없으면 UNKNOWN이며 통과로 두지 않는다", async () => {
    const withoutPolicy = {
      ...SIMULATION,
      savings_portfolio: {
        ...SIMULATION.savings_portfolio,
        result: { ...SIMULATION.savings_portfolio.result, final_policy_status: undefined, final_policy_valid: undefined, validation_reasons: undefined },
      },
    };

    const result = await map(withoutPolicy);

    expect(result.final_policy_status).toBe("UNKNOWN");
    expect(result.final_policy_valid).toBe(false);
  });

  it("저축 절이 NOT_RUN이면 사유를 담아 INFEASIBLE로 만든다", async () => {
    const notRun = {
      as_of: "2026-08-02",
      savings_portfolio: {
        run_status: "NOT_RUN",
        section_schema_version: "savings-portfolio@1.1.0",
        engine_status: null,
        result: null,
        missing_inputs: ["savings_request"],
        reasons: ["저축 요청이 없어 계산하지 않았습니다."],
        assumptions: [],
        policy_sources: [],
      },
    };

    const result = await map(notRun);

    expect(result.status).toBe("INFEASIBLE");
    expect(result.reasons).toContain("저축 요청이 없어 계산하지 않았습니다.");
  });

  it("PARTIAL 상태를 그대로 옮긴다", async () => {
    // 엔진에는 있고 웹 계약에는 없던 값이다. 픽스처 20명에 없어서 드러나지
    // 않았을 뿐, 실시간 경로에서 나오면 파싱이 던진다.
    const partial = {
      ...SIMULATION,
      savings_portfolio: {
        ...SIMULATION.savings_portfolio,
        result: { ...SIMULATION.savings_portfolio.result, status: "PARTIAL" },
      },
    };

    const result = await map(partial);

    expect(result.status).toBe("PARTIAL");
    expect(result.success).toBe(false);
  });

  it("검토한 상품 집계는 실시간 경로에 없으므로 비운다", async () => {
    const result = await map();

    expect(result.evaluation).toBeUndefined();
  });

  it("계약을 통과하는 결과를 만든다", async () => {
    const result = await map();

    expect(portfolioResultSchema.safeParse(result).success).toBe(true);
  });
});
```

- [ ] **Step 3: 실패를 확인한다**

Run: `npm test -- portfolio-result`
Expected: FAIL — `Failed to resolve import "./portfolio-result"`

- [ ] **Step 4: 계약에서 `evaluation`을 optional로 내린다**

`src/lib/contracts/result.ts`:

```ts
  // ELIGIBLE/INELIGIBLE 집계는 배치 파이프라인이 만드는 값이라 실시간
  // SimulationResult에는 없다. 0으로 채우면 "검토한 상품 0건"이라는 거짓이
  // 되므로 없는 상태로 둔다.
  evaluation: z
    .object({
      ELIGIBLE: z.number().int(),
      INELIGIBLE: z.number().int(),
    })
    .optional(),
```

`src/features/dashboard/portfolio-status-notice.tsx`의 `검토한 상품 조합` 줄(`Row` 컴포넌트, 44-47행)을 조건부로 감싼다:

```tsx
          {result.evaluation && (
            <Row
              label="검토한 상품 조합"
              value={`${result.evaluation.ELIGIBLE + result.evaluation.INELIGIBLE}건`}
            />
          )}
```

**같은 단계에서 `PARTIAL`을 계약에 더한다.** 엔진의 `SavingsPortfolioStatus`는 `COMPLETE`·`PARTIAL`·`INFEASIBLE`·`NO_ALLOCATION_REQUIRED` 넷인데 웹 계약에는 `PARTIAL`이 없다. 픽스처 20명에는 없어서 지금까지 드러나지 않았지만, 실시간 경로에서 나오면 `portfolioResultSchema.parse`가 던진다.

`src/lib/contracts/result.ts`:

```ts
export const portfolioStatusSchema = z.enum([
  "COMPLETE",
  // 예산의 일부만 배분된 상태. 배분표가 있으므로 COMPLETE와 같이 그린다.
  "PARTIAL",
  "INFEASIBLE",
  "NO_ALLOCATION_REQUIRED",
]);
```

`src/lib/format/codes.ts`의 `portfolioStatusLabel`에 `PARTIAL: "일부 배분"`을 더한다.

`src/features/dashboard/portfolio-view.tsx`에서 배분표를 그리는 조건을 넓힌다. `PARTIAL`은 배분 결과가 있으므로 "배분하지 못했다" 안내로 보내면 실제로 있는 배분표를 감춘다:

```tsx
      {result.status === "COMPLETE" || result.status === "PARTIAL" ? (
```

미배분액은 `PortfolioCaveats`가 이미 `monthly_unallocated`로 알린다.

- [ ] **Step 5: 결과 매핑을 구현한다**

`src/lib/api/portfolio-result.ts`:

```ts
import type { InputFormValues } from "@/features/input/form-schema";
import type { PersonaProfile } from "@/lib/contracts/persona";
import { type PortfolioResult, portfolioResultSchema } from "@/lib/contracts/result";

type Section = {
  run_status?: string;
  result?: Record<string, unknown> | null;
  reasons?: string[];
  missing_inputs?: string[];
};

function section(simulation: unknown): Section {
  const root = simulation as { savings_portfolio?: Section } | null;
  return root?.savings_portfolio ?? {};
}

/**
 * 저축 절 결과를 대시보드 뷰모델로 옮긴다.
 *
 * 필드 이름은 픽스처와 같다 — 픽스처도 같은 엔진 결과에서 나왔기 때문이다.
 * 계약이 문자열로 받는 금액은 문자열 그대로 넘긴다. 여기서 숫자로 바꾸면
 * 표시용 반올림이 계산용 값을 덮어쓴다.
 */
export function toPortfolioResult(
  simulation: unknown,
  profile: PersonaProfile,
  values: InputFormValues,
): PortfolioResult {
  const sec = section(simulation);
  const payload = sec.result ?? null;
  const asOf = (simulation as { as_of?: string })?.as_of ?? "";

  // 아래 금액들의 "0" 대체는 `payload`가 null일 때 — 즉 저축 절이 NOT_RUN일
  // 때 — 만 쓰인다. 계약이 이 필드들을 필수 문자열로 요구해서 자리를 비울 수
  // 없기 때문이다. 그때 status는 INFEASIBLE이고, 금액을 그리는
  // `PortfolioSummary`는 COMPLETE/PARTIAL에서만 렌더되므로 이 "0"은 화면에
  // 닿지 않는다. 사용자가 보는 것은 `PortfolioStatusNotice`의 사유 목록이다.
  // 이 조건이 바뀌면(예: 요약 카드를 모든 상태에서 그리게 되면) 0과 미계산이
  // 같은 값으로 보이므로, 그때는 계약을 optional로 바꿔야 한다.
  const candidate = {
    persona_id: profile.persona_id,
    display_name: profile.display_name,
    category: profile.category,
    status: (payload?.status as string) ?? "INFEASIBLE",
    success: payload?.status === "COMPLETE",
    coverage_ratio: String(payload?.coverage_ratio ?? "0"),
    monthly_allocated: String(payload?.monthly_allocated ?? "0"),
    monthly_unallocated: String(payload?.monthly_unallocated ?? "0"),
    lump_sum_allocated: String(payload?.lump_sum_allocated ?? "0"),
    lump_sum_unallocated: String(payload?.lump_sum_unallocated ?? "0"),
    expected_total_principal: String(payload?.expected_total_principal ?? "0"),
    expected_maturity_amount: String(payload?.expected_maturity_amount ?? "0"),
    expected_net_interest: String(payload?.expected_net_interest ?? "0"),
    // 판정이 없으면 UNKNOWN이다. PASS로 두면 미판정과 통과가 같은 값이 된다.
    final_policy_status: (payload?.final_policy_status as string) ?? "UNKNOWN",
    final_policy_valid: payload?.final_policy_valid === true,
    reasons: [...((payload?.reasons as string[]) ?? []), ...(sec.reasons ?? [])],
    validation_reasons: (payload?.validation_reasons as string[]) ?? [],
    allocations: (payload?.allocations as unknown[]) ?? [],
    input: {
      age: values.age,
      monthly_income: values.monthly_income,
      monthly_expense: values.monthly_average_expense,
      current_assets: values.current_assets,
      monthly_savings_budget: values.monthly_savings_budget,
      lump_sum_budget: values.lump_sum_budget,
      fund_needed_date: profile.savings.fund_needed_date,
    },
    source: { generator: "live-simulation", as_of: asOf },
  };

  return portfolioResultSchema.parse(candidate);
}
```

- [ ] **Step 6: 결과 매핑 테스트를 통과시킨다**

Run: `npm test -- portfolio-result`
Expected: PASS 5건

- [ ] **Step 7: 오류 타입의 실패하는 테스트를 쓴다**

`src/lib/api/client.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ApiError, apiErrorMessage } from "./errors";

describe("apiErrorMessage", () => {
  it("501은 보관 미설정으로 읽힌다", () => {
    expect(apiErrorMessage(new ApiError(501, "보관 미설정"))).toContain(
      "REPORT_ARCHIVE_PROVIDER",
    );
  });

  it("502는 백엔드가 꺼져 있다는 뜻으로 읽힌다", () => {
    expect(apiErrorMessage(new ApiError(502, ""))).toContain("실행 중인지");
  });

  it("503은 서버가 준 원인을 그대로 보여준다", () => {
    // 폰트 누락과 DB 접속 실패는 다른 문제다. 하나로 뭉개면 고칠 수 없다.
    expect(
      apiErrorMessage(new ApiError(503, "PDF를 만들지 못했습니다: 글꼴 없음")),
    ).toContain("글꼴 없음");
  });

  it("모르는 오류는 지어내지 않는다", () => {
    expect(apiErrorMessage(new Error("boom"))).toContain("boom");
  });
});
```

- [ ] **Step 8: 실패를 확인한다**

Run: `npm test -- client`
Expected: FAIL — `Failed to resolve import "./errors"`

- [ ] **Step 9: 오류 타입과 클라이언트를 구현한다**

`src/lib/api/errors.ts`:

```ts
/** 백엔드가 돌려준 실패. 상태 코드와 서버가 준 사유를 함께 보관한다. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

/**
 * 실패를 화면 문구로 옮긴다.
 *
 * 상태별로 나눈다. 하나의 "불러오지 못했습니다"로 뭉개면 무엇을 고쳐야
 * 하는지 알 수 없다 — 글꼴 미설치와 DB 미연결은 다른 문제다.
 */
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error
      ? `보고서를 불러오지 못했습니다: ${error.message}`
      : "보고서를 불러오지 못했습니다.";
  }

  if (error.status === 501) {
    return "보고서 보관이 설정되지 않았습니다(REPORT_ARCHIVE_PROVIDER).";
  }
  if (error.status === 502 || error.status === 504) {
    return "백엔드에 닿지 못했습니다. 서버가 실행 중인지 확인하세요.";
  }
  if (error.status === 503) {
    return error.detail || "보고서를 만들지 못했습니다.";
  }
  return error.detail || `보고서를 불러오지 못했습니다(${error.status}).`;
}
```

`src/lib/api/client.ts`:

```ts
import { ApiError } from "./errors";
import type { SimulationInputPayload } from "./simulation-input";

async function detailOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : "";
  } catch {
    return "";
  }
}

/** 카드용 계산. AI를 부르지 않아 빠르다. */
export async function postSimulation(
  input: SimulationInputPayload,
): Promise<unknown> {
  const response = await fetch("/api/v1/simulations", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  return response.json();
}

/**
 * 보고서를 만들어 보관하고 그 id를 돌려준다.
 *
 * 응답 본문의 PDF 바이트를 쓰지 않고 id만 받는 이유는, 뷰어가
 * `GET /api/v1/reports/{id}.pdf`를 걸어야 새로고침과 새 탭 열기가 살아 있기
 * 때문이다. 두 번째 요청은 보관된 파일을 읽을 뿐이라 AI도 렌더도 다시
 * 돌지 않는다.
 */
export async function postReportPdf(
  input: SimulationInputPayload,
): Promise<string> {
  const response = await fetch("/api/v1/reports?format=pdf", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }

  const reportId = response.headers.get("X-Report-Id");
  if (!reportId) {
    throw new ApiError(response.status, "응답에 보고서 id가 없습니다.");
  }
  return reportId;
}
```

- [ ] **Step 10: 전체 테스트와 타입 검사**

Run: `npm test && npx tsc --noEmit`
Expected: 전부 PASS

- [ ] **Step 11: 커밋**

```bash
git add src/lib/api/ src/lib/contracts/result.ts src/features/dashboard/portfolio-status-notice.tsx
git commit -m "feat: 백엔드 클라이언트와 결과 매핑을 만든다

실패를 상태별로 나눠 문구를 만든다. 하나로 뭉개면 글꼴 미설치와 DB 미연결을
구분할 수 없다.

evaluation(ELIGIBLE/INELIGIBLE)은 배치 파이프라인 산출물이라 실시간
SimulationResult에 없다. 0으로 채우면 '검토한 상품 0건'이라는 거짓이 되므로
계약에서 optional로 내리고 값이 없으면 그 줄을 감춘다.

정책 판정이 없으면 UNKNOWN이다. PASS로 두면 미판정과 통과가 같은 값이 된다."
```

---

### Task 7: web — 위저드 → 대시보드 폼값 전달

**Files:**
- Create: `housing-finance-web/src/lib/session/input-handoff.ts`
- Modify: `housing-finance-web/src/features/input/input-wizard.tsx:76-81`
- Test: `src/lib/session/input-handoff.test.ts` (신규), `input-wizard.test.tsx` (수정)

**Interfaces:**
- Consumes: `InputFormValues` (Task 3)
- Produces:
  - `export function saveInputHandoff(personaId: string, values: InputFormValues): void`
  - `export function readInputHandoff(personaId: string): InputFormValues | null`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`src/lib/session/input-handoff.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";

import { readInputHandoff, saveInputHandoff } from "./input-handoff";

const VALUES = {
  age: 24,
  household_size: 1,
  monthly_income: 2000000,
  monthly_average_expense: 1200000,
  current_assets: 8000000,
  target_region: "11650",
  target_price: 325000000,
  target_move_in_ym: "2028-07",
  risk_preference: "stability",
  monthly_savings_budget: 500000,
  lump_sum_budget: 0,
  emergency_reserve: 1000000,
  months: 360,
  housing_status: "NO_HOUSE",
  monthly_essential_expense: 1200000,
  exclusive_area_m2: 84,
} as never;

describe("입력 핸드오프", () => {
  beforeEach(() => sessionStorage.clear());

  it("저장한 값을 그대로 돌려준다", () => {
    saveInputHandoff("persona_e", VALUES);

    expect(readInputHandoff("persona_e")).toEqual(VALUES);
  });

  it("다른 페르소나의 값을 돌려주지 않는다", () => {
    // 페르소나를 바꾼 뒤 이전 사람의 입력으로 계산하면 화면과 결과가
    // 서로 다른 사람을 가리킨다.
    saveInputHandoff("persona_e", VALUES);

    expect(readInputHandoff("persona_f")).toBeNull();
  });

  it("저장된 것이 없으면 null이다", () => {
    expect(readInputHandoff("persona_e")).toBeNull();
  });

  it("깨진 값이 들어 있으면 null이다", () => {
    sessionStorage.setItem("hf:input-handoff", "{not json");

    expect(readInputHandoff("persona_e")).toBeNull();
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test -- input-handoff`
Expected: FAIL — `Failed to resolve import "./input-handoff"`

- [ ] **Step 3: 핸드오프를 구현한다**

`src/lib/session/input-handoff.ts`:

```ts
import type { InputFormValues } from "@/features/input/form-schema";

const KEY = "hf:input-handoff";

/**
 * 위저드가 입력한 값을 대시보드로 넘긴다.
 *
 * 두 페이지가 분리돼 있고 URL로 나르기에는 필드가 많다. 서버에 실행 상태를
 * 두지 않기 위해 `sessionStorage`를 쓴다 — 탭을 닫으면 사라지고, 다른
 * 사용자와 섞이지 않는다.
 *
 * 페르소나 id를 함께 저장한다. 페르소나를 바꾼 뒤 이전 사람의 입력으로
 * 계산하면 화면과 결과가 서로 다른 사람을 가리킨다.
 */
export function saveInputHandoff(
  personaId: string,
  values: InputFormValues,
): void {
  sessionStorage.setItem(KEY, JSON.stringify({ personaId, values }));
}

export function readInputHandoff(personaId: string): InputFormValues | null {
  const raw = sessionStorage.getItem(KEY);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as {
      personaId?: string;
      values?: InputFormValues;
    };
    if (parsed.personaId !== personaId || !parsed.values) return null;
    return parsed.values;
  } catch {
    return null;
  }
}
```

- [ ] **Step 4: 테스트를 통과시킨다**

Run: `npm test -- input-handoff`
Expected: PASS 4건

- [ ] **Step 5: 위저드가 저장하게 한다**

`src/features/input/input-wizard.tsx`의 `onSubmit`을 바꾼다. `edited` 계산과 쿼리 파라미터는 유지한다 — 다음 과제에서 안내 문구를 정리한다:

```tsx
  const onSubmit = form.handleSubmit((values) => {
    saveInputHandoff(personaId, values);
    const edited = changedFields(defaultValues, values).length > 0;
    router.push(`/dashboard?persona=${personaId}${edited ? "&edited=1" : ""}`);
  });
```

import를 더한다:

```tsx
import { saveInputHandoff } from "@/lib/session/input-handoff";
```

- [ ] **Step 6: 위저드 테스트를 더한다**

`src/features/input/input-wizard.test.tsx`는 `renderWizard()` 헬퍼와 `SAMPLE` 상수를 이미 갖고 있고, `next/navigation`의 `push`를 목으로 잡아 둔다. 그대로 쓴다. import 한 줄을 더한다:

```tsx
import { readInputHandoff } from "@/lib/session/input-handoff";
```

테스트:

```tsx
it("결과 보기를 누르면 입력값을 대시보드로 넘긴다", async () => {
  const user = userEvent.setup();
  await renderWizard();

  await user.click(screen.getByRole("button", { name: "다음" }));
  await user.click(screen.getByRole("button", { name: "다음" }));
  await user.click(screen.getByRole("button", { name: "결과 보기" }));

  expect(readInputHandoff(SAMPLE)).not.toBeNull();
  expect(push).toHaveBeenCalled();
});
```

이 파일에 `beforeEach`가 이미 있으면 거기에 `sessionStorage.clear()`를 더한다. 없으면 위 테스트 앞에 추가한다 — 앞선 테스트가 남긴 값으로 통과하면 이 테스트는 아무것도 검증하지 않는다.

- [ ] **Step 7: 전체 테스트**

Run: `npm test && npx tsc --noEmit`
Expected: 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add src/lib/session/ src/features/input/input-wizard.tsx src/features/input/input-wizard.test.tsx
git commit -m "feat: 위저드 입력값을 대시보드로 넘긴다

지금까지 '결과 보기'는 페르소나 id만 넘기고 폼 값을 버렸다. 입력 화면이
화면상으로만 동작하고 있었다.

페르소나 id를 함께 저장해 다른 사람의 입력으로 계산하지 않게 한다."
```

---

### Task 8: web — 대시보드 실시간 전환

**Files:**
- Create: `housing-finance-web/src/features/dashboard/live-dashboard.tsx`
- Modify: `housing-finance-web/src/app/dashboard/page.tsx`
- Modify: `housing-finance-web/src/features/dashboard/portfolio-view.tsx`
- Test: `src/features/dashboard/live-dashboard.test.tsx` (신규)

**Interfaces:**
- Consumes: `buildSimulationInput` (Task 5), `postSimulation`·`toPortfolioResult`·`apiErrorMessage` (Task 6), `readInputHandoff` (Task 7), `toFormValues` (Task 3)
- Produces: `export function LiveDashboard({ profile }: { profile: PersonaProfile }): JSX.Element`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`src/features/dashboard/live-dashboard.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { loadProfile } from "@/lib/fixtures/loader";

import { LiveDashboard } from "./live-dashboard";

const PERSONA = "persona_e_college_student_basic";

const SIMULATION = {
  as_of: "2026-08-02",
  savings_portfolio: {
    run_status: "COMPLETED",
    section_schema_version: "savings-portfolio@1.1.0",
    engine_status: "COMPLETE",
    result: {
      status: "COMPLETE",
      coverage_ratio: "1",
      monthly_allocated: "500000",
      monthly_unallocated: "0",
      lump_sum_allocated: "0",
      lump_sum_unallocated: "0",
      expected_total_principal: "12000000",
      expected_maturity_amount: "12300000",
      expected_net_interest: "300000",
      allocations: [],
      reasons: [],
      final_policy_status: "PASS",
      final_policy_valid: true,
      validation_reasons: [],
    },
    missing_inputs: [],
    reasons: [],
  },
};

function mockFetch(handler: (url: string) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo) => handler(String(input))));
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveDashboard", () => {
  it("계산 결과로 포트폴리오를 그린다", async () => {
    mockFetch(() => Response.json(SIMULATION));
    render(<LiveDashboard profile={await loadProfile(PERSONA)} />);

    await waitFor(() =>
      expect(screen.getByText("예적금 포트폴리오")).toBeInTheDocument(),
    );
    expect(screen.getByText("정책 통과")).toBeInTheDocument();
  });

  it("계산 중에는 그 사실을 알린다", async () => {
    mockFetch(() => new Promise(() => {}) as never);
    render(<LiveDashboard profile={await loadProfile(PERSONA)} />);

    expect(screen.getByText(/계산하고 있습니다/)).toBeInTheDocument();
  });

  it("백엔드가 꺼져 있으면 그렇게 말한다", async () => {
    mockFetch(() => Response.json({ detail: "Backend API is unavailable" }, { status: 502 }));
    render(<LiveDashboard profile={await loadProfile(PERSONA)} />);

    await waitFor(() =>
      expect(screen.getByText(/실행 중인지/)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test -- live-dashboard`
Expected: FAIL — `Failed to resolve import "./live-dashboard"`

- [ ] **Step 3: `LiveDashboard`를 구현한다**

`src/features/dashboard/live-dashboard.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";

import { toFormValues } from "@/features/input/form-schema";
import { ReportViewer } from "@/features/report/report-viewer";
import { apiErrorMessage } from "@/lib/api/errors";
import { postSimulation } from "@/lib/api/client";
import { toPortfolioResult } from "@/lib/api/portfolio-result";
import { buildSimulationInput } from "@/lib/api/simulation-input";
import type { PersonaProfile } from "@/lib/contracts/persona";
import type { PortfolioResult } from "@/lib/contracts/result";
import { readInputHandoff } from "@/lib/session/input-handoff";

import { PortfolioView } from "./portfolio-view";

/**
 * 대시보드의 계산 주체.
 *
 * 두 호출은 서로를 기다리지 않는다. 카드는 AI를 부르지 않는
 * `/api/v1/simulations`로 1~2초에 뜨고, 보고서는 AI 두 번과 PDF 렌더를 거쳐
 * 나중에 붙는다. 하나로 묶으면 카드까지 20~30초를 기다린다.
 */
export function LiveDashboard({ profile }: { profile: PersonaProfile }) {
  const [result, setResult] = useState<PortfolioResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 위저드를 거치지 않고 바로 들어온 경우 페르소나 기준값으로 계산한다.
  const values = readInputHandoff(profile.persona_id) ?? toFormValues(profile);
  const input = buildSimulationInput(values, profile);

  useEffect(() => {
    let cancelled = false;

    postSimulation(input)
      .then((simulation) => {
        if (cancelled) return;
        setResult(toPortfolioResult(simulation, profile, values));
      })
      .catch((cause) => {
        if (cancelled) return;
        setError(apiErrorMessage(cause));
      });

    return () => {
      cancelled = true;
    };
    // 입력이 같으면 다시 계산하지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(input)]);

  if (error) {
    return (
      <section className="py-12">
        <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {error}
        </p>
      </section>
    );
  }

  if (!result) {
    return (
      <section className="py-12">
        <p className="text-sm text-brand-muted" role="status">
          입력하신 값으로 계산하고 있습니다…
        </p>
      </section>
    );
  }

  return (
    <>
      <PortfolioView result={result} />
      <ReportViewer input={input} />
    </>
  );
}
```

`ReportViewer`는 Task 9에서 만든다. 이 과제에서는 다음 임시 파일을 두어 컴파일을 통과시키고, Task 9이 내용을 채운다:

`src/features/report/report-viewer.tsx`:

```tsx
"use client";

import type { SimulationInputPayload } from "@/lib/api/simulation-input";

export function ReportViewer({ input: _input }: { input: SimulationInputPayload }) {
  return null;
}
```

- [ ] **Step 4: `PortfolioView`에서 낡은 안내를 뺀다**

`src/features/dashboard/portfolio-view.tsx`의 `edited` prop과 그 안내 블록을 지운다. *"변경한 목표값은 백엔드 시뮬레이션 연동 후 반영됩니다"*는 이제 거짓이다 — 값이 실제로 반영된다.

`props`에서 `edited`를 빼고, `{edited && (...)}` 블록 전체를 지운다.

- [ ] **Step 5: 페이지를 바꾼다**

`src/app/dashboard/page.tsx`:

```tsx
import { LiveDashboard } from "@/features/dashboard/live-dashboard";
import { requirePersonaId } from "@/lib/fixtures/guard";
import { loadProfile } from "@/lib/fixtures/loader";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ persona?: string | string[] }>;
}) {
  const params = await searchParams;
  const personaId = requirePersonaId(params.persona);
  const profile = await loadProfile(personaId);

  return (
    <main>
      <LiveDashboard profile={profile} />
    </main>
  );
}
```

- [ ] **Step 6: 기존 대시보드 테스트를 고친다**

`portfolio-view.test.tsx`·`portfolio-status-notice.test.tsx`에서 `edited={false}` 인자를 전부 지운다. 이 테스트들은 여전히 픽스처를 렌더하며 계속 유효하다 — `PortfolioView`는 순수 표시 컴포넌트다.

- [ ] **Step 7: 전체 테스트와 타입 검사**

Run: `npm test && npx tsc --noEmit`
Expected: 전부 PASS

- [ ] **Step 8: 커밋**

```bash
git add src/features/dashboard/ src/features/report/ src/app/dashboard/page.tsx
git commit -m "feat: 대시보드를 실시간 계산으로 전환한다

지금까지 대시보드는 픽스처 result.json만 읽고 백엔드를 한 번도 부르지
않았다.

두 호출을 분리한다. 카드는 AI를 부르지 않는 /api/v1/simulations로 바로 뜨고
보고서는 뒤따른다. 묶으면 카드까지 AI를 기다린다.

'변경한 목표값은 연동 후 반영됩니다' 안내를 지운다 — 이제 거짓이다."
```

---

### Task 9: web — 보고서 PDF 인라인 뷰어

**Files:**
- Modify: `housing-finance-web/src/features/report/report-viewer.tsx` (Task 8이 만든 임시 파일을 채운다)
- Test: `src/features/report/report-viewer.test.tsx` (신규)

**Interfaces:**
- Consumes: `postReportPdf`·`apiErrorMessage` (Task 6), `SimulationInputPayload`·`FIXED_ACQUISITION_ASSUMPTIONS` (Task 5)
- Produces: `export function ReportViewer({ input }: { input: SimulationInputPayload }): JSX.Element`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`src/features/report/report-viewer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SimulationInputPayload } from "@/lib/api/simulation-input";

import { ReportViewer } from "./report-viewer";

const INPUT = {} as SimulationInputPayload;
const REPORT_ID = "8f6c1c30-3f9e-4a2b-9d51-1c0b2e7a4d88";

function mockFetch(response: Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(() => response));
}

function pdfResponse() {
  return new Response(new Uint8Array([0x25, 0x50, 0x44, 0x46]), {
    status: 200,
    headers: { "X-Report-Id": REPORT_ID, "content-type": "application/pdf" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("ReportViewer", () => {
  it("만드는 동안 시간이 걸린다는 것을 알린다", () => {
    mockFetch(new Promise(() => {}) as never);
    render(<ReportViewer input={INPUT} />);

    expect(screen.getByText(/보고서를 만들고 있습니다/)).toBeInTheDocument();
  });

  it("보관된 PDF를 iframe으로 띄운다", async () => {
    mockFetch(pdfResponse());
    render(<ReportViewer input={INPUT} />);

    await waitFor(() => {
      const frame = screen.getByTitle("실행 보고서");
      expect(frame).toHaveAttribute("src", `/api/v1/reports/${REPORT_ID}.pdf`);
    });
  });

  it("새 탭에서 열 수 있는 링크를 함께 둔다", async () => {
    mockFetch(pdfResponse());
    render(<ReportViewer input={INPUT} />);

    await waitFor(() =>
      expect(screen.getByRole("link", { name: /새 탭/ })).toHaveAttribute(
        "href",
        `/api/v1/reports/${REPORT_ID}.pdf`,
      ),
    );
  });

  it("보관이 설정되지 않았으면 그 이름을 알려준다", async () => {
    mockFetch(Response.json({ detail: "보관 미설정" }, { status: 501 }));
    render(<ReportViewer input={INPUT} />);

    await waitFor(() =>
      expect(screen.getByText(/REPORT_ARCHIVE_PROVIDER/)).toBeInTheDocument(),
    );
  });

  it("렌더 실패는 서버가 준 원인을 그대로 보여준다", async () => {
    mockFetch(
      Response.json(
        { detail: "PDF를 만들지 못했습니다: 한글 글꼴이 임베드되지 않았습니다" },
        { status: 503 },
      ),
    );
    render(<ReportViewer input={INPUT} />);

    await waitFor(() =>
      expect(screen.getByText(/한글 글꼴/)).toBeInTheDocument(),
    );
  });

  it("고정한 취득 가정을 화면에 밝힌다", () => {
    mockFetch(new Promise(() => {}) as never);
    render(<ReportViewer input={INPUT} />);

    expect(screen.getByText(/고급주택이 아닌 것으로/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 실패를 확인한다**

Run: `npm test -- report-viewer`
Expected: FAIL — `Unable to find an element with the text: /보고서를 만들고 있습니다/` (Task 8의 임시 구현이 `null`을 돌려준다)

- [ ] **Step 3: 뷰어를 구현한다**

설계 §3.8은 "AI 키가 없으면 그 사실을 뷰어 상단에 표시"라고 적었으나 **그렇게 만들 수 없다.** `format=pdf`는 PDF 바이트와 `X-Report-Id`만 돌려주고 `notes`·`figures_only_sections`는 `format=json` 응답에만 있다. 그것을 알아내려고 요청을 한 번 더 보내면 AI와 렌더가 다시 돈다.

대신 그 문구는 **보고서 문서 안에** 실린다 — 파이프라인이 `notes`에 담고 양식이 그것을 렌더한다. 사용자는 PDF를 열면 본다. 뷰어에 따로 만들지 않는다.

`src/features/report/report-viewer.tsx`를 통째로 바꾼다:

```tsx
"use client";

import { useEffect, useState } from "react";

import { postReportPdf } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import {
  FIXED_ACQUISITION_ASSUMPTIONS,
  type SimulationInputPayload,
} from "@/lib/api/simulation-input";

/**
 * 보고서 PDF를 대시보드 안에서 그대로 보여준다.
 *
 * 응답 본문의 바이트를 blob URL로 쓰지 않고 `X-Report-Id`로 GET URL을 다시
 * 건다. 그래야 새로고침과 새 탭 열기가 살아 있다. 두 번째 요청은 보관된
 * 파일을 읽을 뿐이라 AI도 렌더도 다시 돌지 않는다.
 *
 * 스크롤·페이지 번호·확대는 브라우저 내장 PDF 뷰어가 처리한다.
 */
export function ReportViewer({ input }: { input: SimulationInputPayload }) {
  const [reportId, setReportId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    postReportPdf(input)
      .then((id) => {
        if (!cancelled) setReportId(id);
      })
      .catch((cause) => {
        if (!cancelled) setError(apiErrorMessage(cause));
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(input)]);

  const href = reportId ? `/api/v1/reports/${reportId}.pdf` : null;

  return (
    <section className="grid gap-3 pb-12">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-xl font-bold tracking-[-0.03em]">실행 보고서</h2>
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-semibold text-accent underline"
          >
            새 탭에서 열기
          </a>
        )}
      </div>

      <ul className="m-0 grid list-none gap-1 p-0 text-xs text-brand-muted">
        {FIXED_ACQUISITION_ASSUMPTIONS.map((note) => (
          <li key={note}>· {note}</li>
        ))}
      </ul>

      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          {error}
        </p>
      )}

      {!error && !href && (
        <p
          className="rounded-xl border border-line p-4 text-sm text-brand-muted"
          role="status"
        >
          보고서를 만들고 있습니다. 계산과 서술 검증을 거치므로 20~30초 걸립니다.
        </p>
      )}

      {href && (
        <iframe
          title="실행 보고서"
          src={href}
          className="h-[80vh] w-full rounded-xl border border-line"
        />
      )}
    </section>
  );
}
```

- [ ] **Step 4: 테스트를 통과시킨다**

Run: `npm test -- report-viewer`
Expected: PASS 6건

- [ ] **Step 5: 전체 테스트와 타입 검사**

Run: `npm test && npx tsc --noEmit`
Expected: 전부 PASS

- [ ] **Step 6: 손으로 확인한다**

core 서버와 SSH 터널을 띄운 상태에서 `npm run dev`를 돌리고 `/personas`에서 페르소나 하나를 골라 위저드를 끝까지 통과한다.

확인할 것:
1. 카드가 먼저 뜨고 하단에 "보고서를 만들고 있습니다"가 보인다
2. 잠시 뒤 PDF가 iframe에 뜨고 **한글이 두부가 아니다**
3. iframe 안에서 스크롤이 되고 페이지 번호가 보인다
4. "새 탭에서 열기"가 같은 PDF를 연다
5. Step 1에서 필수생활비를 크게 올리면 대출 한도가 줄어든다

- [ ] **Step 7: 커밋**

```bash
git add src/features/report/
git commit -m "feat: 대시보드 하단에 보고서 PDF를 인라인으로 띄운다

blob URL이 아니라 X-Report-Id로 GET URL을 다시 건다. 그래야 새로고침과
새 탭 열기가 살아 있다. 두 번째 요청은 보관된 파일을 읽을 뿐이라 AI도
렌더도 다시 돌지 않는다.

스크롤·페이지 번호·확대는 브라우저 내장 뷰어가 처리한다 — pdf.js를
도입하지 않는다.

고정한 취득 가정 셋을 뷰어 상단에 밝힌다. 특히 고급주택 아님은 취득세를
작게 잡는 방향이라 조용히 두지 않는다."
```

---

## 완료 기준

- [ ] core: `python -m pytest -q` 통과, `python -m ruff check <손댄 파일>` 통과
- [ ] web: `npm test` 통과, `npx tsc --noEmit` 통과
- [ ] 위저드를 통과하면 대시보드에 실계산 카드가 뜬다
- [ ] 대시보드 하단 iframe에 PDF가 뜨고 한글이 읽힌다
- [ ] 백엔드를 끄면 "백엔드에 닿지 못했습니다"가, 터널을 닫으면 503의 원인이 그대로 보인다

## 알려진 것 — 구현 중 당황하지 말 것

**페르소나 20명 전원이 목표 미달이다.** 직전 작업(`2026-08-01`)에서 엔진으로 실측한 결과다. 따라서 보고서에는 대출 한도 0원(basic·poor 14명 중 13명)과 "5. 목표 미달 시 필요한 보완" 절이 실린다. **이것이 정답이다.** 숫자가 작다고 입력이나 매핑을 의심하지 말 것.

**`q` 페르소나의 부족액은 61,035원이다.** 이것도 버그가 아니라 DSR 40% 상한이다.

**데모에 필요한 것 다섯 가지.** 하나라도 없으면 Task 6이 만든 오류 화면이 뜬다.

1. core 서버 실행 (`BACKEND_API_URL`, 기본 `http://127.0.0.1:8000`)
2. SSH 터널 (PDF 보관이 DB에 메타데이터를 쓴다)
3. `.env`의 `REPORT_ARCHIVE_PROVIDER=filesystem`
4. weasyprint + Noto Sans CJK KR
5. `GEMINI_API_KEY` — **없어도 된다.** 없으면 보고서에 수치만 실린다
