# 페르소나 매매(HOME_PURCHASE) 전환 설계

- 작성일: 2026-08-01
- 상태: 승인됨 (2026-08-01 매물 데이터 방침 개정)
- 범위: `housing-finance-core`(주), `housing-finance-web`(종)

## 1. 배경

대학생 페르소나 20명은 전부 월세보증금 목표(`target_housing_type: "monthly_rent"`)로
생성되어 있다. 서비스를 주택구매(`HOME_PURCHASE`) 축으로 전환하기로 했고,
매물 데이터도 이미 전부 `TransactionType.SALE`이라 전월세 축은 더 이상 쓰지 않는다.

**목표 금액의 의미가 바뀐다.** `target_price`에는 보증금(300만~8,000만원)이 들어
있다. 플래그만 매매로 바꾸면 "300만원짜리 매매 주택"이라는 값이 남는다.

## 2. 결정과 근거

| # | 결정 | 근거 |
| --- | --- | --- |
| 1 | 스펙 키를 `target_purchase_price`로 교체한다 | 값의 의미가 바뀌므로 이름도 바뀌어야 한다. 보증금이라는 이름의 필드에 매매가를 넣지 않는다 |
| 2 | 전월세 제거는 페르소나 데이터와 웹 표면까지만 | core의 `GoalType`과 전세대출 상품 3종·Rule Pack·한도표는 검증된 살아있는 기능이다. 지우면 상품군이 죽는다 |
| 3 | 목표 시점 2028-07 유지 | "지금은 부족하니 얼마를 더 모으면 되는가"가 이 서비스의 본래 질문이라 미달도 유의미한 결과다 |
| 4 | 페르소나 `target_region`은 손대지 않는다 | 지역은 Step 1에서 사용자가 고르는 값이고 페르소나 값은 초기값일 뿐이다 |
| 5 | **가상 매물을 만들지 않는다** | 신뢰성을 주장할 방법이 없다. 아래 2.2 참조 |
| 6 | **매물 스냅샷은 이 스펙에서 손대지 않는다** | 실거래 어댑터는 독립된 설계 문제다. 아래 2.3 참조 |

### 2.1 결정 4를 초안에서 뒤집은 이유

초안에서는 페르소나 목표지역이 매물 보유 지역과 어긋난다고 보아 재배치를
설계에 넣었다. 확인해 보니 `DesiredHomePanel`의 `<select>`가 서울 25개 구와
"전체"를 모두 노출하고 목표가격도 자유 입력이며, 실거래 표에서 금액을 클릭해
채울 수도 있다. 페르소나 값은 `toFormValues()`가 넣는 초기값이므로 정합 대상이
아니다. "강남구를 목표로 하는 affluent 5명" 문제도 여기서 함께 사라진다.

### 2.2 결정 5 — 가상 매물을 철회한 이유

초안의 §3.4는 실거래 분포에서 가상 매물을 파생시키자고 했다. 철회한다.

"실거래 분포에서 파생했다"는 것은 **가격 분포가 그럴듯하다**는 뜻이지 그 집이
존재한다는 뜻이 아니다. `source_type: MOCK`을 붙이고 `license_note`에 "가상"이라
적어도, 화면과 보고서 PDF에 뜨는 것은 구체적인 단지명과 가격이다. 사용자는 그것을
시장 정보로 읽는다. 특히 **PDF는 저장·공유되면서 맥락이 떨어져 나간다** — PDF만
본 사람에게는 매물 추천서로 보인다.

이는 이 저장소가 반복해서 금지하는 "모르는 것을 그럴듯한 값으로 채우기"에
해당한다. 신뢰성을 주장할 수 있는 것과 없는 것은 이렇게 갈린다.

| 대상 | 주장 가능 | 근거 |
| --- | --- | --- |
| 실거래 가격·면적·층·거래일 | 가능 | 국토부 실거래 데이터 |
| 취득세·LTV·DSR 계산 | 가능 | 출처·기준일이 붙은 규제표 |
| 매물의 존재 여부 | **불가능** | 데이터가 없다 |

실제 매물 데이터는 API로 확보하지 못했다. 확보되지 않은 것을 지어내지 않는다.

### 2.3 결정 6 — 실거래 어댑터를 분리한 이유

대안으로 채택한 방향은 **실거래를 "참고 물건"으로 쓰는 것**이다. 매물이라 부르지
않고, 실거래 한 건을 "이런 집" 기준점으로 삼아 그 가격에 산다면 어떻게 되는지를
계산한다. 지어내는 값이 없다 — 전부 실거래 사실이거나 엔진 계산 결과다.

이 방향은 옳지만 **이 스펙에 넣지 않는다.** 독립된 설계 문제이기 때문이다.

- `ListingStatus`를 어떻게 모델링할지 정해야 한다. 실거래는 "지금 살 수 있는가"에
  답이 없으므로 `ACTIVE`로 뭉갤 수 없다(§22.1). 그런데 `property_search.py:20`이
  비-ACTIVE를 걸러내고 `property_affordability.py:58`은 `ValueError`를 던진다 —
  하드 게이트가 두 곳이다
- `PropertyDataSourceType`에 실거래 출처를 추가해야 한다. 이 값은
  `PropertyAffordabilityAIHandoff.source`를 타고 보고서 AI까지 흐르므로,
  보고서가 후보의 성격을 알 수 있는 자리이기도 하다
- 역세권 필터와 지도 마커는 실거래에 위경도·역 정보가 없어 동작하지 않는다.
  못 하는 것을 못 한다고 표시하는 설계가 필요하다
- 화면·보고서 문구에서 "지금 살 수 있다"는 함의를 제거해야 한다

그리고 **웹에 매물 검색 화면이 아직 없다.** 라우트는 `/`, `/input`, `/personas`,
`/dashboard`, `/report`뿐이고 `property`를 소비하는 프론트 코드가 없다. 매물
검색은 백엔드에만 존재하므로 이 결정을 미뤄도 사용자에게 보이는 것이 없다.

따라서 `property_listings.v1.json`(6건)과 `property_search_cases.v1.json`은 계약
검증용 픽스처로 **그대로 둔다.** 테스트 5개가 여기에 의존한다.

## 3. 설계

### 3.1 범위

**바꾼다**: core 페르소나 생성기의 대학생 목표, 웹 페르소나 스키마의 전월세 필드.

**바꾸지 않는다**: core의 `GoalType`(3값 유지), 전세대출 상품·Rule Pack·한도표,
매물 스냅샷과 검색 케이스 픽스처, `ListingStatus`, 검색·판정 서비스, Step 1 폼
필드, 보고서 API.

### 3.2 페르소나 목표 전환 — `app/data_pipeline/mydata/generate_all.py`

`COLLEGE_STUDENT_VARIANT_SPECS`의 세 키를 하나로 교체한다.

```
target_lease_deposit  ┐
target_monthly_rent   ├─→  target_purchase_price
target_management_fee ┘
```

프로필 빌더(`generate_all.py` 984-989행 부근)의 출력이 이렇게 바뀐다.

| 필드 | 지금 | 바꾼 뒤 |
| --- | --- | --- |
| `target_housing_type` | `"monthly_rent"` | `"purchase"` |
| `target_price` | `spec["target_lease_deposit"]` | `spec["target_purchase_price"]` |
| `target_lease_deposit` | 있음 | 제거 |
| `target_monthly_rent` | 있음 | 제거 |
| `target_management_fee` | 있음 | 제거 |
| `target_region` | 그대로 | 그대로 |
| `target_move_in_ym` | `202807` | 그대로 |

하드코딩된 `persona_e`(709-716행 부근)도 같은 형태로 맞춘다.
`generation_metadata`의 "월세 보증금 마련 가능성" 문구와 `generated_assumptions`의
전월세 키도 함께 정리한다.

`target_housing_type`의 새 값은 `"purchase"`로 한다. 기존 값이 소문자 스네이크
어휘(`monthly_rent`)이므로 그 관용을 따른다. 이 필드는 마이데이터 프로필 계약의
값이고 API 계약의 `GoalType.HOME_PURCHASE`와는 계층이 다르다 — 웹 어댑터가
후속 스펙에서 둘을 잇는다.

#### target_purchase_price를 정하는 방법

**그 페르소나 `target_region`의 실거래 하위 분위값**에서 가져온다. 손으로 고른
숫자를 흩뿌리지 않는다. 사용자가 초기값을 고치지 않고 넘어가도 "그 구에서 실제로
거래되는 가격"이 되고, Step 1의 실거래 표와 축이 어긋나지 않는다.

조회에는 DB 터널이 필요하다(`docs/LOCAL_DB_TUNNEL.md`). 조회는 **한 번만 하고 그
결과를 생성기에 상수로 박는다** — 생성기가 DB에 의존하면 터널이 닫힌 환경에서
픽스처를 만들 수 없게 된다. 조회에 쓴 SQL과 기준일을 스펙 키 옆 주석에 남긴다.

터널을 열 수 없으면 이 항목만 막히므로, 그때는 값을 지어내지 말고 작업을 멈추고
보고한다.

### 3.3 웹 표면 정리 — `housing-finance-web`

- `src/lib/contracts/persona.ts`: `goal`에서 `target_lease_deposit`,
  `target_monthly_rent`, `target_management_fee` 제거
- `src/lib/format/codes.ts`: `housingTypeLabel`에 `purchase: "매매"` 추가.
  `monthly_rent`는 `current_housing_type`이 계속 쓰므로 **남긴다**
- `src/features/input/step-input.tsx` 48행: "월세 보증금 시나리오로 생성된 원본
  데이터" 설명 문구를 매매 기준으로 갱신
- `npm run build:fixtures`로 20명 픽스처 재생성

픽스처는 core의 mydata 출력에서 빌드되므로(`scripts/build-fixtures.mjs`가
`../housing-finance-core/app/data_pipeline/mydata`를 읽는다) **웹 픽스처를 직접
수정하지 않는다.**

### 3.4 검증

1. `python -m pytest -q` — 매물 픽스처와 서비스를 건드리지 않았으므로 전부
   통과해야 한다
2. `python -m ruff check app` — 손댄 파일에만 건다
3. 생성기 재실행 → `npm run build:fixtures` → 웹 테스트 통과
4. 웹에서 페르소나 하나를 열어 Step 1~3이 매매 목표로 표시되는지 육안 확인

## 4. 알려진 영향

목표 금액이 실거래 하위 대역으로 올라가면 구매 가능 판정을 받는 페르소나가
줄어든다. 아래는 그 대역을 **2억으로 가정한** 손계산 추정이며 엔진을 돌린 값이
아니다. 3.2의 실거래 조회를 마친 뒤 실제 값으로 다시 확인해야 한다.

| 구간 | 2028년 자기자본 추정 | 2억 기준 |
| --- | --- | --- |
| affluent m·n·o·p·q | 6,160만~1.92억 | 가능 5명 |
| affluent l | 4,900만 | 미달 |
| basic 7명 | 200만~1,460만 | 미달 |
| poor 7명 | 100만~200만 | 미달 |

서울 전역이 투기과열지구이고 페르소나 전원이 `is_first_home_buyer: True`이므로
`housing_status = FIRST_HOME_BUYER` → LTV 70%가 적용된다. 2억이면 자기자본 약
6,000만원과 취득비용이 필요하다. DSR 40% 기준으로는 위 5명이 모두 통과할 것으로
보인다.

미달이 다수인 것은 결정 3에서 받아들인 결과다 — "얼마를 더 모으면 되는가"가
이 서비스의 질문이다.

## 5. 후속 스펙

이 스펙은 다음 세 단계의 토대다. 각각 별도 스펙·계획으로 진행한다.

1. **실거래 참고 물건 어댑터** — 실거래를 "매물"이라 부르지 않고 참고 물건으로
   금융 판정에 넣는다. 2.3에 적은 네 가지 설계 결정이 여기 속한다
2. **Step 1 폼 확장** — `loan_request` 필수 3개(만기·주택보유상태·필수생활비)와
   생애최초 여부, 그리고 취득비용 5개를 입력받는다. 대출·종합추천·스트레스·
   전략비교 4개 절이 여기서 열린다
3. **보고서 API 연동** — Step 1~3 값을 `SimulationInput`으로 변환해
   `POST /api/v1/reports`를 호출하고 결과를 화면과 PDF로 노출한다
