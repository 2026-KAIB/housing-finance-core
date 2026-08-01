# 페르소나 매매(HOME_PURCHASE) 전환 설계

- 작성일: 2026-08-01
- 상태: 승인됨
- 범위: `housing-finance-core`(주), `housing-finance-web`(종)

## 1. 배경

대학생 페르소나 20명은 전부 월세보증금 목표(`target_housing_type: "monthly_rent"`)로
생성되어 있다. 서비스를 주택구매(`HOME_PURCHASE`) 축으로 전환하기로 했고,
매물 데이터도 이미 전부 `TransactionType.SALE`이라 전월세 축은 더 이상 쓰지 않는다.

전환에는 세 가지가 걸려 있다.

**하나. 목표 금액의 의미가 바뀐다.** `target_price`에는 보증금(300만~8,000만원)이
들어 있다. 플래그만 매매로 바꾸면 "300만원짜리 매매 주택"이라는 값이 남는다.

**둘. 웹에 가격 축이 다른 두 데이터가 동시에 붙어 있다.** Step 1의 실거래 표는
실제 서울 아파트 DB(`v_valid_trades`)를 읽어 수억~수십억을 보여주는데, 매물 검색이
읽는 스냅샷은 4,500만~8,400만원이다. 페르소나와 무관하게 이 축이 어긋나 있다.

**셋. 매물 스냅샷은 데모 데이터가 아니라 계약 검증용 픽스처다.** 주소가
"관악구 가상동·예시동·샘플동·테스트동"이고 파일에 "개발과 계약 검증만을 위한
완전 가상 매물"이라고 적혀 있다. 테스트 5개 파일이 이 6건과
`property_search_cases.v1.json`의 `expected_listing_ids`에 의존한다.

## 2. 결정과 근거

| # | 결정 | 근거 |
| --- | --- | --- |
| 1 | 목표 금액을 매물 데이터셋과 같은 대역으로 맞춘다 | 사용자가 고칠 **초기값**이므로 목적은 정합이 아니라 "고치지 않고 넘어가도 말이 되는 값" |
| 2 | 전월세 제거는 페르소나 데이터와 웹 표면까지만 | core의 `GoalType`과 전세대출 상품 3종·Rule Pack·한도표는 검증된 살아있는 기능이다. 지우면 상품군이 죽는다 |
| 3 | 목표 시점 2028-07 유지 | "지금은 부족하니 얼마를 더 모으면 되는가"가 이 서비스의 본래 질문이라 미달도 유의미한 결과다 |
| 4 | 페르소나 `target_region`은 손대지 않는다 | 지역은 Step 1에서 사용자가 고르는 값이고 페르소나 값은 초기값일 뿐이다 |
| 5 | 매물은 실거래 분포에서 파생한 가상 매물로 확충한다 | 사용자가 25개 구 중 아무거나 고를 수 있으므로 넓게 깔려야 하고, 실거래 표와 가격 축이 이어져야 한다 |
| 6 | 계약 검증용 픽스처와 데모 데이터셋을 분리한다 | 기존 6건을 갈아끼우면 테스트 5개가 깨진다. 분리하면 둘 다 각자의 목적을 지킨다 |

### 결정 4를 뒤집은 이유

초안에서는 페르소나 목표지역이 매물 보유 지역과 어긋난다고 보아 재배치를
설계에 넣었다. 확인해 보니 `DesiredHomePanel`의 `<select>`가 서울 25개 구와
"전체"를 모두 노출하고 목표가격도 자유 입력이며, 실거래 표에서 금액을 클릭해
채울 수도 있다. 페르소나 값은 `toFormValues()`가 넣는 초기값이므로 정합 대상이
아니다. "강남구를 목표로 하는 affluent 5명" 문제도 여기서 함께 사라진다.

## 3. 설계

### 3.1 범위

**바꾼다**: core 페르소나 생성기의 대학생 목표, 웹 페르소나 스키마의 전월세 필드,
매물 데모 데이터셋.

**바꾸지 않는다**: core의 `GoalType`(3값 유지), 전세대출 상품·Rule Pack·한도표,
`property_listings.v1.json`과 `property_search_cases.v1.json`, Step 1 폼 필드,
보고서 API. Step 1 폼 확장과 보고서 연동은 후속 스펙이다.

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

`target_purchase_price` 값은 **그 페르소나의 `target_region`에 있는 데모 매물의
최저가 부근**으로 정한다. 손으로 고른 숫자를 흩뿌리지 않고 데이터에서 파생하면,
사용자가 초기값을 고치지 않고 넘어가도 "그 구에서 실제로 보이는 가격"이 된다.
3.4의 데이터셋을 먼저 만들고 그 결과에서 역으로 채운다.

`target_housing_type`의 새 값은 `"purchase"`로 한다. 기존 값이 소문자 스네이크
어휘(`monthly_rent`)이므로 그 관용을 따른다. 이 필드는 마이데이터 프로필 계약의
값이고 API 계약의 `GoalType.HOME_PURCHASE`와는 계층이 다르다 — 웹 어댑터가
후속 스펙에서 둘을 잇는다.

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

### 3.4 매물 데모 데이터셋

```
sample_data/property_listings/
├── property_listings.v1.json      ← 6건 고정. 계약 검증용. 테스트 5개가 의존. 손대지 않음
├── property_search_cases.v1.json  ← 그대로
└── property_listings.demo.json    ← 신규. 실거래 분포 파생
```

**설정 전환에는 코드 변경이 필요 없다.** `Settings`에 `env_prefix`가 없으므로
`property_listing_json_path` 필드는 `PROPERTY_LISTING_JSON_PATH` 환경변수로 이미
덮어써진다. `.env.example`에 데모 경로를 주석으로 안내하는 것으로 충분하다.
테스트는 기본값(`v1`)을 그대로 읽으므로 깨지지 않는다.

생성 스크립트는 `scripts/`에 둔다(기존 `check_region_trades_db.py`와 같은 자리).
`v_valid_trades`에서 구·면적·가격 분포를 읽어 가상 매물을 만들되 다음을 지킨다.

- `source_type`은 `MOCK`을 유지하고, `license_note`에 **"실거래 분포에서 파생한
  가상 매물"** 로 명시한다. 체결 이력을 판매 중 매물로 둔갑시키지 않는다 —
  `property_trade.py`가 "이 DB에는 판매 중인 매물이 없다"고 못박고 있다
- `listing_id`는 `DEMO-<시군구코드>-<연번>` 형식으로 기존 `MOCK-*`와 분리한다
- 법정동명은 실제 값을 쓰고 단지명은 가상으로 만든다
- 서울 25개 구를 모두 덮는다. **구당 4~6건, 총 100~150건**을 목표로 한다 —
  검색 결과가 한 화면에 담기면서도 정렬·필터가 의미를 갖는 최소 규모다
- **표본은 각 구 실거래의 하위 가격 구간에서 뽑는다.** 면적과 가격은 같은
  거래에서 온 쌍을 유지한다(층마다 가격이 다르므로 중위값으로 뭉개지 않는다는
  `property_trade.py`의 규약과 같은 이유). 가상화하는 것은 단지명과
  `listing_id`뿐이고 가격·면적·법정동은 실거래에서 온 값이다
- 하위 구간을 쓰는 이유는 대학생 페르소나의 자산 규모에서 구매 가능/미달 판정이
  갈리는 지점이 거기이기 때문이다. 전 구간을 뽑으면 20명 전원이 미달로 수렴한다
- 금액은 문자열, 면적은 ㎡, 시각은 타임존 포함 ISO 8601 —
  `sample_data/property_listings/README.md`의 단위 규칙을 그대로 따른다

DB에 접근할 수 없는 환경에서도 저장소 전체 테스트가 통과해야 하므로, 이 스크립트는
**빌드 단계가 아니라 수동 실행**이며 산출물(JSON)을 커밋한다.

### 3.5 검증

1. `python -m pytest -q` — 매물 픽스처를 건드리지 않았으므로 전부 통과해야 한다
2. `python -m ruff check app scripts` — 손댄 파일에만 건다
3. 생성기 재실행 → `npm run build:fixtures` → 웹 테스트 통과
4. 웹에서 페르소나 하나를 열어 Step 1~3이 매매 목표로 표시되는지 육안 확인

## 4. 알려진 영향

매물 대역이 실거래 수준으로 올라가면 구매 가능 판정을 받는 페르소나가 줄어든다.
아래는 하위 구간 대표값을 **2억으로 가정한** 손계산 추정이며 엔진을 돌린 값이
아니다. 3.4의 데이터셋을 만든 뒤 실제 분포로 다시 확인해야 한다.

| 구간 | 2028년 자기자본 추정 | 2억 매물 기준 |
| --- | --- | --- |
| affluent m·n·o·p·q | 6,160만~1.92억 | 가능 5명 |
| affluent l | 4,900만 | 미달 |
| basic 7명 | 200만~1,460만 | 미달 |
| poor 7명 | 100만~200만 | 미달 |

서울 전역이 투기과열지구이고 페르소나 전원이 `is_first_home_buyer: True`이므로
`housing_status = FIRST_HOME_BUYER` → LTV 70%가 적용된다. 2억 매물이면 자기자본
약 6,000만원과 취득비용이 필요하다. DSR 40% 기준으로는 위 5명이 모두 통과할
것으로 보인다.

미달이 다수인 것은 결정 3에서 받아들인 결과다 — "얼마를 더 모으면 되는가"가
이 서비스의 질문이다.

## 5. 후속 스펙

이 스펙은 다음 두 단계의 토대다. 각각 별도 스펙·계획으로 진행한다.

1. **Step 1 폼 확장** — `loan_request` 필수 3개(만기·주택보유상태·필수생활비)와
   생애최초 여부, 그리고 취득비용 5개를 입력받는다. 대출·종합추천·스트레스·
   전략비교 4개 절이 여기서 열린다
2. **보고서 API 연동** — Step 1~3 값을 `SimulationInput`으로 변환해
   `POST /api/v1/reports`를 호출하고 결과를 화면과 PDF로 노출한다
