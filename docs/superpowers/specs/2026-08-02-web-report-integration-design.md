# 웹 보고서 연동 설계 (2026-08-02)

Step 1 입력 폼을 확장해 보고서의 대출·전략비교 절을 열고, 최종 '예적금
포트폴리오' 대시보드 하단에 보고서 PDF를 인라인 뷰어로 붙인다.

## 1. 배경

`2026-08-01-persona-home-purchase-design.md` §6이 후속 스펙 세 건을 남겼다.
이 문서는 그중 둘(**Step 1 폼 확장**, **보고서 API 연동**)을 하나의 수직
슬라이스로 묶는다. 남은 하나(실거래 참고 물건 어댑터)는 이 문서의 범위가
아니다.

현재 상태를 확인한 결과, 두 요청 사이에 **요청되지 않았지만 없으면 둘 다
무의미해지는 항목**이 하나 있었다.

### 1.1 폼 값이 대시보드에 도달하지 않는다

`housing-finance-web/src/features/input/input-wizard.tsx:76-81`:

```ts
const edited = changedFields(defaultValues, values).length > 0;
router.push(`/dashboard?persona=${personaId}${edited ? "&edited=1" : ""}`);
```

사용자가 입력한 값이 여기서 버려진다. 넘어가는 것은 페르소나 ID와 "고쳤음"
플래그뿐이고, 대시보드는 `loadResult(personaId)`로 픽스처 `result.json`을
읽는다. Step 1 폼은 현재 화면상으로만 동작한다.

따라서 실제 작업은 셋이다.

```
Step1 폼 확장  →  [폼값 → SimulationInput → 백엔드 호출]  →  보고서 PDF 표시
   (요청됨)              (요청되지 않음, 필수)                  (요청됨)
```

### 1.2 이미 있어서 만들지 않아도 되는 것

| 있는 것 | 위치 |
| --- | --- |
| 백엔드 프록시 | `web/src/app/api/[...path]/route.ts` → `BACKEND_API_URL` |
| 시뮬레이션 엔드포인트 | `POST /api/simulations` → `SimulationResult` |
| 보고서 PDF 생성 | `POST /api/reports?format=pdf` |
| 보관 PDF 조회 | `GET /api/reports/{report_id}.pdf` |
| 인라인 응답 헤더 | `reports.py:69-83` — `Content-Disposition: inline` + `X-Report-Id` |

`reports.py:70-75`의 주석이 의도를 명시한다 — *"브라우저 내장 뷰어에서 열리도록
inline으로 내보낸다. attachment면 다운로드로 떨어져 웹에서 바로 볼 수 없다."*
요청하신 "PDF 자체가 바로 보이고 스크롤되는" 형태는 이 엔드포인트를 iframe에
물리면 그대로 나온다. pdf.js 같은 라이브러리를 도입하지 않는다.

## 2. 결정과 근거

### 2.1 결정 1 — 대시보드 전체를 실시간으로 전환한다

선택지는 셋이었다.

1. 보고서만 실시간, 카드는 픽스처 유지
2. **대시보드 전체 실시간** ← 채택
3. 실시간 우선, 실패 시 픽스처 폴백

1번은 화면 상단 숫자와 하단 보고서 숫자의 출처가 달라 어긋날 수 있다. 3번은
화면에 뜬 숫자가 실계산인지 목업인지 사용자가 구분할 수 없게 만든다 — 모름과
값을 뭉개지 않는다는 §22.1과 정면으로 충돌한다.

### 2.2 결정 2 — PDF 렌더러를 설치한다 (HTML 대체로 돌아서지 않는다)

`weasyprint`는 선택 의존성이다. `pyproject.toml:26-33`이 이유를 적어 두었다 —
Pango·cairo 같은 시스템 라이브러리를 요구해서 Windows 로컬에서 pip만으로는
동작하지 않기 때문에 기본 의존성에서 뺐다.

이 맥의 실측:

| 구성요소 | 상태 |
| --- | --- |
| pango 1.57.0_1 | 설치됨 |
| cairo 1.18.4 | 설치됨 |
| libffi 3.6.0 | 설치됨 |
| gdk-pixbuf | 미설치 — weasyprint 53+는 요구하지 않는다 |
| weasyprint | 미설치 |
| Noto Sans CJK KR | 미설치 |

`format=html`로 물러서는 선택지가 있었으나 채택하지 않았다. 요청은 "PDF 자체가
바로 보이게"였고, 남은 설치가 두 줄뿐이며, 코드 변경이 필요 없다.

#### 2.2.1 폰트 함정 — NotoSansKR은 쓸 수 없다

`~/Library/Fonts`에 `NotoSansKR-Black.ttf` 등이 이미 있지만 **이 폰트로는 안
된다.** 두 곳에서 걸린다.

- `app/reports/pdf.py:187-192`의 `_looks_korean_capable()`은 폰트 이름에
  `cjk`·`malgun`·`nanum`·`gothic`·`batang`·`gulim`·`dotum` 중 하나가 있어야
  통과시킨다. `NotoSansKR`에는 없다.
- `app/reports/templates/official.py:45-46`의 CSS 폰트 스택은
  `"Noto Serif CJK KR", "Noto Sans CJK KR"`을 지명한다.

`app/reports/pdf.py:32-34`의 주석이 정확히 이 혼동을 경고한다 — *"실제 패밀리
이름은 'Noto Sans CJK KR'이며 'Noto Sans KR'이 아니다. 이름을 틀리면 폰트가
설치돼 있어도 fontconfig가 못 찾아 두부가 난다."*

따라서 `font-noto-sans-cjk` 캐스크를 설치한다. 그러면 CSS 스택과 두부 검사가
동시에 맞아떨어져 **코드 변경이 필요 없다.**

### 2.3 결정 3 — PDF 경로는 DB를 요구한다. 우회하지 않는다

`app/services/report_archive.py:113-121`은 PDF를 파일시스템에 쓴 뒤
**메타데이터를 DB에 넣는다**(`insert_report`). DB에 닿지 못하면
`ReportArchiveUnavailable` → 503이다.

즉 보고서 데모에는 SSH 터널이 열려 있어야 하고 `reports` 테이블이 있어야 한다.

보관을 건너뛰고 PDF 바이트만 돌려주는 경로를 core에 새로 낼 수도 있었지만
채택하지 않았다. 두 가지 이유다.

- 보관을 건너뛰면 `GET /api/reports/{id}.pdf`라는 **iframe에 물릴 URL이
  사라진다.** blob URL로 대체할 수 있으나 새로고침·새 탭 열기가 깨진다.
- 보고서는 규제 수치와 가정을 담은 문서다. 무엇을 언제 어떤 기준일로 냈는지
  남기지 않는 경로를 새로 만드는 것은 이 저장소의 방향과 반대다.

### 2.4 결정 4 — 페르소나 재무 데이터를 다시 건드리지 않는다

새로 받는 네 값 모두 기존 데이터에서 안전하게 유도되거나 사용자가 고르는
값이다. `generate_all.py`에 새 항목을 만들 이유가 없다.

이것은 직전 작업(`2026-08-01`)의 §2.2와 같은 판단이다. 그 문서는 페르소나 자본을
부풀리려다 두 번 실패한 기록을 남겼다. 재무 데이터는
`tests/data_pipeline/test_college_student_goals.py`가 20명분 기준값으로 고정하고
있으며, 이 작업은 그 테스트를 건드리지 않는다.

### 2.5 결정 5 — 기본값은 "모르면 한도가 커지는 쪽"의 반대로 둔다

`CLAUDE.md`의 표를 그대로 적용한다.

| 필드 | 기본값 | 반대로 두면 |
| --- | --- | --- |
| `housing_status` | **무주택**(NO_HOUSE) | 생애최초는 LTV 70%, 무주택은 40%. 유리한 쪽을 기본값으로 두면 한도가 커진다 |
| `monthly_essential_expense` | **월평균지출과 동일** | 필수생활비가 작을수록 Buffer(`max(300_000, essential*0.10)`)가 작아져 한도가 커진다 |
| `exclusive_area_m2` | 84 | 목표가가 `exclu_use_ar <= 85` 실거래 p05에서 나왔다 |
| `months` | 360 (30년) | 주담대 표준. 사용자가 고르는 값이지 모르는 값이 아니다 |

`monthly_essential_expense`의 기본값이 특히 중요하다. **월평균지출 전액을
필수로 보는 것은 데이터를 지어내지 않으면서 동시에 보수적인 유일한 선택이다.**
"지출의 70%가 필수" 같은 비율을 도입하면 근거 없는 숫자가 계산에 들어가고, 그
방향은 한도를 키운다. 실제 필수생활비를 아는 사용자는 값을 낮추면 된다.

`housing_status` 기본값은 사실 정확도를 일부 포기한 선택이다. 대학생이 첫 집을
사는 것은 명백히 생애최초다. 그러나 생애최초는 사용자가 **주장해야 하는 사실**로
두는 편이 낫다 — 기본값이 LTV를 70%로 열어 두면, 아무것도 고르지 않은 사용자가
가장 유리한 한도를 받는다.

### 2.6 결정 6 — 저축 포트폴리오 정책 검증을 `SimulationResult`에 노출한다

설계 검토 중 발견했다. **웹 대시보드가 쓰는 값 세 개가 API 응답에 없다.**

`portfolioResultSchema`(`web/src/lib/contracts/result.ts:34-37`)의
`final_policy_status`·`final_policy_valid`·`validation_reasons`를 화면이 실제로
쓴다.

- `web/src/features/dashboard/portfolio-summary.tsx:26` — `final_policy_status === "PASS"`일 때 배지
- `web/src/features/dashboard/portfolio-caveats.tsx:16` — `validation_reasons`를 주의사항으로

그런데 `app/services/simulation_result.py:223-226`의
`build_calculation_section(savings_portfolio_result, ...)`는 엔진 결과
(`SavingsPortfolioResult`)만 감싼다. 정책 검증은
`SavingsPortfolioOutcome.validation`(`app/services/savings_portfolio.py:92-100`)에
**존재하지만 조립 단계에서 버려진다.**

세 선택지 중 (a)를 채택한다.

- (a) **core에서 직렬화를 추가한다** ← 채택
- (b) 웹 계약에서 optional로 내리고 "확인되지 않음"으로 표시
- (c) 다른 값에서 유도

(b)는 §22.1이 금지하는 뭉개기다. 엔진이 **실제로 계산한** 판정을, 노출을
빠뜨렸다는 이유로 "모름"으로 표시하게 된다. 모름과 값은 같은 상태가 아니다.
(c)는 불가능하다 — 정책 검증은 Rule Pack 재검증 결과이므로 다른 필드에서
복원할 수 없다.

이 결정은 설계 검토 초반의 "core는 환경 구축만 하고 코드는 건드리지 않는다"는
판단을 뒤집는다. 그 판단은 `SimulationResult`가 대시보드에 필요한 것을 모두
담고 있다는 **확인하지 않은 가정**에 기대고 있었다. 가정을 확인한 결과 세
필드가 비어 있었다.

### 2.7 결정 7 — 느린 호출과 빠른 호출을 분리한다

`POST /api/reports`는 AI 두 번(작성·판정)과 PDF 렌더를 거친다. `POST
/api/simulations`는 AI를 부르지 않는다. 두 요청을 하나로 묶으면 카드까지 AI를
기다린다.

세 아키텍처 중 A를 채택한다.

- **A: 대시보드가 계산 주체** ← 채택. 위저드가 폼값을 `sessionStorage`에 넣고
  이동, 대시보드가 두 호출을 독립적으로 발사.
- B: 위저드가 계산. "결과 보기" 후 20~30초 빈 화면.
- C: Next 라우트 핸들러가 오케스트레이션. 실행 결과 저장소가 새로 생긴다 —
  이 단계에 필요 없다.

A의 대가는 대시보드가 서버 컴포넌트에서 클라이언트 컴포넌트로 바뀌는 것이다.

## 3. 설계

### 3.1 범위

**포함**

- core 환경 구축(weasyprint·폰트·`.env`)
- core 저축 포트폴리오 정책 검증 직렬화(결정 6)
- 웹 Step 1 폼 4개 필드 추가 + `current_assets` 필수화
- 웹 폼값 → `SimulationInput` 매핑 모듈
- 웹 대시보드 실시간 전환
- 웹 보고서 PDF 인라인 뷰어

**제외**

- 실거래 참고 물건 어댑터 (별도 후속 스펙)
- `_required_amount`가 목표 시점 저축을 반영하도록 고치는 일 (별도 후속 스펙)
- 페르소나 데이터 재생성 (결정 4)
- 인증·다중 사용자 세션

### 3.2 환경 구축 — core

```bash
brew install --cask font-noto-sans-cjk
python -m pip install -e ".[pdf]"
```

`.env`에 다음을 추가한다. **값을 문서·로그·오류 메시지에 출력하지 않는다.**

```
REPORT_ARCHIVE_PROVIDER=filesystem
```

`report_storage_root`는 `app/core/config.py:67`의 기본값 `var/reports`를 쓴다.

**검증**: 페르소나 하나로 `POST /api/reports?format=pdf`를 호출해 200과
`%PDF` 매직바이트를 확인하고, `embedded_font_names()`로 CJK 폰트가 임베드됐는지
본다. 두부 검사(`verify_korean_glyphs`)가 통과하지 못하면 이 단계는 실패다.

### 3.3 정책 검증 직렬화 — core

`build_simulation_result()`가 `SavingsPortfolioOutcome.validation`을 받아
`savings_portfolio` 절에 함께 싣는다. 웹 계약이 이미 쓰는 이름을 그대로 쓴다.

| 웹 계약 필드 | 출처 |
| --- | --- |
| `final_policy_status` | `validation.status` (`PASS`/`FAIL`/`UNKNOWN`) |
| `final_policy_valid` | `validation.valid` |
| `validation_reasons` | `validation.reasons` |

검증이 없는 경우(저축 절 자체가 `NOT_RUN`)에는 이 필드들을 채우지 않는다.
0이나 `PASS`로 채우지 않는다.

### 3.4 Step 1 폼 확장 — web

`src/features/input/form-schema.ts`에 네 필드를 더하고 `current_assets`를
필수로 올린다.

| 필드 | 형태 | 기본값 |
| --- | --- | --- |
| `months` | select — 120·240·360·480 | 360 |
| `housing_status` | select — `HousingStatus` 5종 | `NO_HOUSE` |
| `monthly_essential_expense` | 금액 | `monthly_average_expense`와 동일 |
| `exclusive_area_m2` | 숫자(㎡) | 84 |

`current_assets`가 `won.optional()`인 것은 고쳐야 한다.
`FinancialSnapshot.liquid_assets`는 필수이므로, 비어 있으면 0으로 채우고 싶은
압력이 생긴다. 그것은 직전 작업의 최종 리뷰에서
`scripts/check_persona_affordability.py`가 걸렸던 결함과 같은 형태다.

화면 배치: `months`·`housing_status`·`monthly_essential_expense`는 새 그룹
**"대출 조건"**에, `exclusive_area_m2`는 기존 **희망 주택** 패널에 둔다.
전용면적은 목표 주택의 사실이지 대출 조건이 아니다.

`StepReview`(step 3. 입력 확인)에 네 값을 모두 표시한다. 확인 화면이 계산에
들어가는 값을 다 보여주지 않으면 그 화면의 이름이 거짓이 된다.

### 3.5 폼값 → `SimulationInput` 매핑 — web

`src/lib/api/simulation-input.ts` 하나가 경계를 전담한다. 이 모듈 밖에서는
`SimulationInput` 모양을 알지 못한다.

**유도하는 값**

| 대상 | 출처 |
| --- | --- |
| `profile.annual_income` | `profile.finance.annual_income_verified` |
| `profile.is_married` | `profile.basic.marital_status` |
| `profile.is_first_home_buyer` | `housing_status === "FIRST_HOME_BUYER"` |
| `housing_goal.target_date` | `target_move_in_ym` (YYYY-MM → 해당 월 1일) |
| `acquisition_costs.household_home_count_after_purchase` | `housing_status`에서 유도 |
| `savings_request.fund_needed_date` | `profile.savings.fund_needed_date` |

**이 서비스 범위에서 고정하는 값**

| 필드 | 값 | 근거 |
| --- | --- | --- |
| `buyer_is_corporation` | `false` | 개인 사용자 대상 서비스 |
| `is_registered_housing` | `true` | 아파트 매매 |
| `is_luxury_home` | `false` | **가정.** 고급주택이면 취득세가 중과되므로 이 값은 비용을 작게 잡는 방향이다 |

마지막 항목은 가정이며, 화면에 가정임을 명시한다. 현재 목표가 대역(2.6억~9.4억)
에서는 해당이 없으나 사용자가 목표가를 직접 바꿀 수 있으므로 조용히 두지
않는다.

`acquisition_costs` 블록이 없으면
`app/services/housing_scenarios.py:131-140`이 시나리오를 만들지 않는다 — *"매매가
만으로 시나리오를 세우면 필요 자금을 실제보다 작게 잡습니다."* 그래서 이 블록을
채우는 것이 전략비교 절을 여는 조건이다.

### 3.6 대시보드 실시간 전환 — web

```
위저드 제출 → sessionStorage[폼값] → /dashboard?persona=...
                                        ├─ POST /api/simulations   → 카드 (1~2초)
                                        └─ POST /api/reports?format=pdf → 뷰어 (20~30초)
```

두 호출은 서로를 기다리지 않는다.

`SimulationResult.savings_portfolio` → 기존 `PortfolioResult` 뷰모델로 매핑하는
함수를 `src/lib/api/portfolio-result.ts`에 둔다. 필드 이름이 이미 일치하므로
(`coverage_ratio`·`monthly_allocated`·`allocations` 등) 매핑은 얇다. §3.3의
직렬화 추가로 나머지 세 필드도 채워진다.

`sessionStorage`에 폼값이 없는 채로 `/dashboard`에 직접 오는 경로(페르소나
목록에서 바로 진입)는 페르소나 프로필과 §3.4의 기본값으로 입력을 구성한다.
위저드를 통과한 것과 같은 값이 된다.

### 3.7 보고서 PDF 뷰어 — web

`src/features/report/report-viewer.tsx`.

1. `POST /api/reports?format=pdf` 호출
2. 응답 헤더 `X-Report-Id`를 읽는다
3. `<iframe src={"/api/reports/" + id + ".pdf"} />`

스크롤·페이지 번호·확대는 브라우저 내장 PDF 뷰어가 처리한다. 높이는 `80vh`
고정, 상단에 새 탭에서 열기 링크를 둔다.

응답 본문의 PDF 바이트를 blob URL로 쓰지 않고 GET URL을 다시 부르는 이유는
새로고침과 새 탭 열기가 살아 있어야 하기 때문이다. 두 번째 요청은 보관된 파일을
읽을 뿐이라 AI도 렌더도 다시 돌지 않는다.

### 3.8 오류 처리

각 실패를 구분해서 보여준다. 하나의 "보고서를 불러오지 못했습니다"로 뭉개지
않는다.

| 상황 | 화면 |
| --- | --- |
| 501 (보관 미설정) | "보고서 보관이 설정되지 않았습니다(REPORT_ARCHIVE_PROVIDER)" |
| 503 (렌더·보관 실패) | 서버가 준 원인 그대로. 폰트 누락·DB 접속 실패가 여기 온다 |
| 502 (백엔드 없음) | "백엔드가 실행 중인지 확인하세요" |
| AI 키 없음 | 보고서는 **수치만**으로 나온다. 그 사실을 뷰어 상단에 표시 |
| 절이 `NOT_RUN` | 보고서 안의 `missing_inputs`가 어떤 필드가 없는지 이름으로 |

AI 키가 없을 때 `app/reports/ai_explanation/gemini.py:75-77`이 남기는 문구는
*"환경변수 GEMINI_API_KEY를 설정하면 AI 설명이 추가됩니다"*이다. 보고서 전체를
버리지 않는다는 규약대로 수치는 그대로 실린다.

### 3.9 검증

**core**

- `savings_portfolio` 절에 세 필드가 실리는지, 검증이 없을 때 채우지 않는지
- PDF 경로: 200 · `%PDF` 매직바이트 · CJK 폰트 임베드

**web**

- 폼 스키마: 네 필드의 필수·기본값, `current_assets`를 비우면 실패하는지
- 매핑: 폼값 → `SimulationInput`의 유도·고정 값이 표대로인지
- 매핑: `SimulationResult` → `PortfolioResult`
- 뷰어: 상태 네 가지(대기·생성중·표시·실패)와 §3.8의 오류 구분
- 기존 대시보드 테스트가 픽스처가 아닌 주입된 결과로 도는지

**수동**

- 페르소나 하나로 위저드를 끝까지 통과해 대시보드에서 PDF를 스크롤한다

## 4. 조사 결과 (2026-08-02)

| 확인 항목 | 결과 |
| --- | --- |
| `weasyprint` | 미설치. `pyproject.toml`의 `[pdf]` 선택 의존성 |
| pango·cairo·libffi | 설치됨 |
| Noto Sans CJK KR | 미설치. `NotoSansKR`은 있으나 쓸 수 없다(§2.2.1) |
| `report_archive_provider` 기본값 | `"none"` (`app/core/config.py:64`) |
| `report_storage_root` 기본값 | `var/reports` (`app/core/config.py:67`) |
| PDF 보관의 DB 의존 | 있음. `insert_report`가 메타데이터를 쓴다 |
| `X-Report-Id` 헤더 | 있음 (`reports.py:81`) |
| `POST /api/simulations` | 있음. `SimulationResult` 반환 |
| `result.json`의 정체 | `SimulationResult`가 아니라 웹 전용 뷰모델. `build-fixtures.mjs:226`이 `college_student_portfolio_results.json`에서 만든다 |
| 정책 검증 3필드 | `SimulationResult`에 없음 → §2.6 |

## 5. 알려진 영향

### 5.1 사용자가 실제로 보게 될 내용

직전 작업의 실측대로 **페르소나 20명 전원이 목표 미달**이다. 따라서 보고서에는
다음이 실린다.

- 대출 한도 0원 — basic·poor 14명 중 13명 (`persona_j`만 20,690,381원)
- **"5. 목표 미달 시 필요한 보완"** 절 (`app/reports/templates/form.py`의
  `FORM_SECTIONS`에 있는 정식 절)

화면이 비는 것이 아니라 이것이 정답이다. 직전 설계 §2.6이 기록했듯 구매 불가여도
대출 절을 억제하지 않는다.

### 5.2 데모 실행 요건

보고서를 띄우려면 다음이 모두 필요하다. 하나라도 없으면 §3.8의 오류 화면이
나온다.

1. core 서버 실행 (`BACKEND_API_URL`, 기본 `http://127.0.0.1:8000`)
2. SSH 터널 (PDF 보관이 DB에 쓴다 — §2.3)
3. `REPORT_ARCHIVE_PROVIDER=filesystem`
4. weasyprint + Noto Sans CJK KR
5. `GEMINI_API_KEY` — **없어도 된다.** 없으면 수치만 실린다

### 5.3 건드리지 않는 것

- 페르소나 재무 데이터와 `test_college_student_goals.py`의 20명분 기준값
- `generate_all.py` → 픽스처 빌드 체인
- 보고서 양식·AI 파이프라인·기계 검증

## 6. 후속 스펙

이 문서의 범위 밖으로 남긴다.

1. **실거래 참고 물건 어댑터** — `2026-08-01` 설계 §6에서 이어짐
2. **`_required_amount`가 목표 시점 저축을 반영** — 엔진이 "오늘 살 수 있는가"에
   답하고 있어 `q`의 부족액이 61,035원으로 나온다. 목표 시점까지의 저축을
   반영하면 넘는다
3. **p05 상수의 재현 가능한 출처** — 생성기 주석에 기준일이 없다
4. **`scripts/`를 CI에 포함** — `testpaths = ["tests"]`라 점검 스크립트가 돌지
   않는다. 엔진·금리표·상품 카탈로그가 바뀌면 "20명 전원 미달"이라는 측정이
   조용히 낡는다
