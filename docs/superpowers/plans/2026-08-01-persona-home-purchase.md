# 페르소나 매매(HOME_PURCHASE) 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대학생 페르소나 20명의 목표를 월세보증금에서 주택매매로 전환하고, 웹 계약에서 전월세 필드를 제거한다.

**Architecture:** 단일 출처는 core의 `generate_all.py`다. 여기서 페르소나 프로필을 생성하면 웹의 `build-fixtures.mjs`가 읽어 픽스처를 만든다. 따라서 core를 먼저 바꾸고, 산출물을 재생성한 뒤, 웹 계약을 맞추고 픽스처를 재빌드하는 순서로 간다. 페르소나의 소득·지출·자산·저축은 한 값도 바꾸지 않는다 — 목표가와 초기 목표지역만 바꾼다.

**Tech Stack:** Python 3.12 / pytest / ruff (core), Node + vitest / zod (web)

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-08-01-persona-home-purchase-design.md`. 충돌하면 설계가 우선한다.
- **페르소나의 `monthly_income`, `monthly_expense`, `checking_balance`, `savings_balance`, `term_deposit_balance`, `monthly_savings_budget`을 바꾸지 않는다.** 설계 결정 4다.
- **`basic`·`poor` 14명의 `target_region`을 바꾸지 않는다.** `affluent` 5명만 옮긴다(`q`는 강남 유지).
- 목표가는 아래 표의 값을 그대로 쓴다. 새로 조회하거나 반올림하지 않는다.
- `ruff format`을 디렉터리 전체에 돌리지 않는다. 린트는 손댄 파일에만 건다.
- 매물 스냅샷(`sample_data/property_listings/`)과 검색·판정 서비스는 건드리지 않는다.
- `.env` 값을 읽거나 출력하지 않는다.
- 커밋은 현재 브랜치(`jpyo`)에 쌓는다. `main`에 직접 커밋하지 않는다.

### 확정된 목표가 상수

2026-08-01 조회. 대상 75,240건(계약일 2025-07-01 ~ 2026-07-22).

```sql
SELECT sgg_cd,
       percentile_disc(0.05) WITHIN GROUP (ORDER BY deal_amount_won) AS p05
  FROM v_valid_trades
 WHERE exclu_use_ar <= 85 AND contract_date >= '2025-01-01'
 GROUP BY sgg_cd;
```

| 페르소나 id | `target_region` | 구 | `target_purchase_price` | 지역 이동 |
| --- | --- | --- | --- | --- |
| `persona_e_college_student_basic` | `11650` | 서초 | `325_000_000` | |
| `persona_f_college_student_02_basic` | `11290` | 성북 | `390_000_000` | |
| `persona_g_college_student_03_basic` | `11260` | 중랑 | `262_500_000` | |
| `persona_h_college_student_04_basic` | `11350` | 노원 | `337_000_000` | |
| `persona_i_college_student_05_basic` | `11560` | 영등포 | `300_000_000` | |
| `persona_j_college_student_06_basic` | `11440` | 마포 | `550_000_000` | |
| `persona_k_college_student_07_basic` | `11500` | 강서 | `365_000_000` | |
| `persona_l_college_student_08_affluent` | `11530` | 구로 | `233_000_000` | **11680 → 11530** |
| `persona_m_college_student_09_affluent` | `11260` | 중랑 | `262_500_000` | **11680 → 11260** |
| `persona_n_college_student_10_affluent` | `11305` | 강북 | `260_000_000` | **11680 → 11305** |
| `persona_o_college_student_11_affluent` | `11320` | 도봉 | `285_000_000` | **11680 → 11320** |
| `persona_p_college_student_12_affluent` | `11215` | 광진 | `259_500_000` | **11290 → 11215** |
| `persona_q_college_student_13_affluent` | `11680` | 강남 | `370_000_000` | |
| `persona_r_college_student_14_poor` | `11350` | 노원 | `337_000_000` | |
| `persona_s_college_student_15_poor` | `11320` | 도봉 | `285_000_000` | |
| `persona_t_college_student_16_poor` | `11230` | 동대문 | `281_700_000` | |
| `persona_u_college_student_17_poor` | `11500` | 강서 | `365_000_000` | |
| `persona_v_college_student_18_poor` | `11200` | 성동 | `460_000_000` | |
| `persona_w_college_student_19_poor` | `11710` | 송파 | `660_000_000` | |
| `persona_x_college_student_20_poor` | `11620` | 관악 | `372_500_000` | |

---

## File Structure

**core (`housing-finance-core`)**

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `app/data_pipeline/mydata/generate_all.py` | 페르소나 원본 정의와 마이데이터 생성 | 스펙 키 교체, 프로필 빌더, argv 가드 |
| `tests/data_pipeline/test_college_student_goals.py` | 20명 프로필의 목표 계약 고정 | **신규** |
| `app/data_pipeline/mydata/persona_*/user_profile.json` | 생성기 산출물 | 재생성 |
| `docs/superpowers/specs/2026-08-01-persona-home-purchase-design.md` | 설계 | Task 5에서 실측 반영 |

**web (`housing-finance-web`)**

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `src/lib/contracts/persona.ts` | 페르소나 zod 계약 | `goal`에서 전월세 3필드 제거 |
| `src/lib/contracts/persona.test.ts` | 계약 테스트 | 픽스처에서 3필드 제거 |
| `src/lib/format/codes.ts` | 코드 → 한국어 라벨 | `purchase: "매매"` 추가 |
| `src/features/input/step-input.tsx` | Step 1 화면 | 48행 설명 문구 |
| `scripts/build-fixtures.mjs` | core 산출물 → 웹 픽스처 | `goal` 매핑에서 3필드 제거 |
| `src/mocks/fixtures/**`, `public/fixtures/**` | 픽스처 | 재빌드 |

---

## Task 1: core 생성기를 매매 목표로 전환한다

**Files:**
- Modify: `app/data_pipeline/mydata/generate_all.py`
- Test: `tests/data_pipeline/test_college_student_goals.py` (신규)

**Interfaces:**
- Consumes: 없음 (첫 작업)
- Produces: `generate_all.py`의 팩토리들이 반환하는 `persona["profile"]`이 다음을 만족한다.
  - `profile["target_housing_type"] == "purchase"`
  - `profile["target_price"]`는 위 표의 `target_purchase_price` 정수
  - `"target_lease_deposit"`, `"target_monthly_rent"`, `"target_management_fee"` 키가 **없다**
  - 스펙 딕셔너리의 키 이름은 `target_purchase_price`
  - 임포트 가능 API: `college_student_variant_factories() -> tuple[Callable[[], dict], ...]` (19개), `persona_e() -> dict`

- [ ] **Step 1: 모듈을 pytest에서 안전하게 임포트할 수 있게 만든다**

`generate_all.py:23`이 **임포트 시점에 `sys.argv`를 읽는다.** pytest로 임포트하면 `OUT_ROOT`가 pytest의 인자 문자열이 되어, 누군가 나중에 `generate()`를 테스트에서 부르면 엉뚱한 경로에 파일을 쓴다. 테스트를 붙이기 전에 막는다.

`app/data_pipeline/mydata/generate_all.py`의 22-24행을 이렇게 바꾼다.

```python
def _default_out_root():
    return os.path.dirname(os.path.abspath(__file__))


# 임포트 시점에 sys.argv를 읽지 않는다 — pytest로 임포트하면 pytest의 인자가
# 출력 경로가 된다. 명령줄 인자는 __main__ 블록에서만 읽는다.
OUT_ROOT = _default_out_root()
SELECTED_PERSONA_ID = None
```

그리고 파일 맨 아래 `if __name__ == "__main__":` 블록의 첫 줄에 다음 두 줄을 넣는다(기존 `print(f"출력: {OUT_ROOT}\n")` **앞**).

```python
    OUT_ROOT = sys.argv[1] if len(sys.argv) > 1 else _default_out_root()
    SELECTED_PERSONA_ID = sys.argv[2] if len(sys.argv) > 2 else None
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/data_pipeline/test_college_student_goals.py`를 새로 만든다.

```python
"""대학생 페르소나 20명의 목표 계약을 고정한다.

월세보증금에서 매매로 전환한 뒤, 전월세 필드가 되살아나거나 목표가가
조용히 바뀌는 것을 막는다. 목표가는 실거래 p05에서 온 값이라
'그럴듯한 숫자'로 대체되면 안 된다.
"""

import pytest

from app.data_pipeline.mydata.generate_all import (
    college_student_variant_factories,
    persona_e,
)

# 설계 문서 2.3의 표. 실거래 p05(전용 85m2 이하, 2025-01-01 이후), 2026-08-01 조회.
EXPECTED_GOALS = {
    "persona_e_college_student_basic": ("11650", 325_000_000),
    "persona_f_college_student_02_basic": ("11290", 390_000_000),
    "persona_g_college_student_03_basic": ("11260", 262_500_000),
    "persona_h_college_student_04_basic": ("11350", 337_000_000),
    "persona_i_college_student_05_basic": ("11560", 300_000_000),
    "persona_j_college_student_06_basic": ("11440", 550_000_000),
    "persona_k_college_student_07_basic": ("11500", 365_000_000),
    "persona_l_college_student_08_affluent": ("11530", 233_000_000),
    "persona_m_college_student_09_affluent": ("11260", 262_500_000),
    "persona_n_college_student_10_affluent": ("11305", 260_000_000),
    "persona_o_college_student_11_affluent": ("11320", 285_000_000),
    "persona_p_college_student_12_affluent": ("11215", 259_500_000),
    "persona_q_college_student_13_affluent": ("11680", 370_000_000),
    "persona_r_college_student_14_poor": ("11350", 337_000_000),
    "persona_s_college_student_15_poor": ("11320", 285_000_000),
    "persona_t_college_student_16_poor": ("11230", 281_700_000),
    "persona_u_college_student_17_poor": ("11500", 365_000_000),
    "persona_v_college_student_18_poor": ("11200", 460_000_000),
    "persona_w_college_student_19_poor": ("11710", 660_000_000),
    "persona_x_college_student_20_poor": ("11620", 372_500_000),
}

RENT_KEYS = ("target_lease_deposit", "target_monthly_rent", "target_management_fee")


def _personas():
    return [factory() for factory in (persona_e, *college_student_variant_factories())]


def test_all_twenty_college_students_are_generated():
    assert len(_personas()) == 20


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_goal_is_home_purchase(persona):
    profile = persona["profile"]
    assert profile["target_housing_type"] == "purchase"


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_rent_fields_are_gone(persona):
    profile = persona["profile"]
    present = [key for key in RENT_KEYS if key in profile]
    assert present == [], f"전월세 필드가 남아 있습니다: {present}"


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_target_region_and_price_match_the_spec(persona):
    region, price = EXPECTED_GOALS[persona["id"]]
    profile = persona["profile"]
    assert profile["target_region"] == region
    assert profile["target_price"] == price


@pytest.mark.parametrize("persona", _personas(), ids=lambda p: p["id"])
def test_finances_are_untouched(persona):
    """설계 결정 4 — 재무 값은 한 값도 바꾸지 않는다.

    전환 이전 값을 그대로 박아 둔다. 목표를 매매로 옮기면서 '이 소득으로는
    무리니 조금만 올리자'는 유혹이 생기는데, 그 시도는 두 번 다 비현실적인
    값으로 무너졌다(설계 2.2). 여기서 막는다.
    """
    income, expense, savings = EXPECTED_FINANCES[persona["id"]]
    profile = persona["profile"]
    assert profile["monthly_income"] == income
    assert profile["monthly_average_expense"] == expense
    assert persona["savings_preferences"]["monthly_savings_budget"] == savings
```

`EXPECTED_FINANCES`는 `RENT_KEYS` 아래에 둔다.

```python
# 전환 이전 값. (월소득, 월평균지출, 월저축예산)
EXPECTED_FINANCES = {
    "persona_e_college_student_basic": (800_000, 700_000, 100_000),
    "persona_f_college_student_02_basic": (900_000, 700_000, 200_000),
    "persona_g_college_student_03_basic": (1_200_000, 900_000, 300_000),
    "persona_h_college_student_04_basic": (1_100_000, 850_000, 250_000),
    "persona_i_college_student_05_basic": (800_000, 750_000, 50_000),
    "persona_j_college_student_06_basic": (1_500_000, 1_100_000, 400_000),
    "persona_k_college_student_07_basic": (1_000_000, 900_000, 100_000),
    "persona_l_college_student_08_affluent": (2_000_000, 1_000_000, 1_000_000),
    "persona_m_college_student_09_affluent": (3_000_000, 1_200_000, 1_800_000),
    "persona_n_college_student_10_affluent": (4_000_000, 1_800_000, 2_200_000),
    "persona_o_college_student_11_affluent": (2_500_000, 1_500_000, 1_000_000),
    "persona_p_college_student_12_affluent": (1_800_000, 900_000, 900_000),
    "persona_q_college_student_13_affluent": (5_000_000, 2_000_000, 3_000_000),
    "persona_r_college_student_14_poor": (600_000, 550_000, 50_000),
    "persona_s_college_student_15_poor": (800_000, 650_000, 50_000),
    "persona_t_college_student_16_poor": (1_000_000, 950_000, 50_000),
    "persona_u_college_student_17_poor": (500_000, 520_000, 0),
    "persona_v_college_student_18_poor": (700_000, 700_000, 0),
    "persona_w_college_student_19_poor": (900_000, 800_000, 20_000),
    "persona_x_college_student_20_poor": (400_000, 600_000, 0),
}
```

- [ ] **Step 3: 테스트를 돌려 실패를 확인한다**

Run: `python -m pytest tests/data_pipeline/test_college_student_goals.py -q`
Expected: FAIL — `test_goal_is_home_purchase`가 `'monthly_rent' != 'purchase'`로, `test_rent_fields_are_gone`이 3개 키가 남아 있다고 떨어진다.

- [ ] **Step 4: 변형 스펙 19개의 키를 교체한다**

`COLLEGE_STUDENT_VARIANT_SPECS`의 각 항목에서 아래 세 줄을 지우고 한 줄로 바꾼다. **각 스펙의 `"id"` 값으로 찾아** Global Constraints의 표에서 값을 가져온다(줄 번호로 찾지 말 것 — 편집하면서 밀린다).

```python
# 지운다
"target_lease_deposit": 6_000_000,
"target_monthly_rent": 250_000,
"target_management_fee": 50_000,

# 넣는다 (예: persona_f_college_student_02_basic)
"target_purchase_price": 390_000_000,
```

`affluent` 5명은 `"target_region"`도 함께 바꾼다.

```python
"target_region": "11530",   # l: 11680 → 구로구
"target_region": "11260",   # m: 11680 → 중랑구
"target_region": "11305",   # n: 11680 → 강북구
"target_region": "11320",   # o: 11680 → 도봉구
"target_region": "11215",   # p: 11290 → 광진구
```

`q`(`persona_q_college_student_13_affluent`)의 `target_region`은 `11680` 그대로 둔다.

- [ ] **Step 5: 프로필 빌더의 출력을 바꾼다**

`generate_all.py` 984-989행 부근(`"target_housing_type": "monthly_rent",`로 시작하는 블록)을 이렇게 바꾼다.

```python
            "target_housing_type": "purchase",
            "target_region": spec["target_region"],
            # 실거래 p05(전용 85m2 이하, 2025-01-01 이후)에서 온 값이다.
            # 조회 SQL과 기준일은 설계 문서 3.2에 있다.
            "target_purchase_price": spec["target_purchase_price"],
            "target_price": spec["target_purchase_price"],
            "target_move_in_ym": target_move_in_ym,
```

`target_lease_deposit`, `target_monthly_rent`, `target_management_fee` 세 줄은 지운다.

- [ ] **Step 6: 변형 스펙의 generation_metadata를 정리한다**

1026행 부근의 문구를 바꾼다.

```python
            "purpose": (
                "기대 결과를 미리 정하지 않고 해당 학생의 재무 사실로 "
                "예적금 평가와 주택 구매 가능성을 관찰한다."
            ),
```

1037-1038행의 `generated_assumptions`에서 아래 두 줄을 지우고 한 줄로 바꾼다.

```python
# 지운다
"target_lease_deposit": spec["target_lease_deposit"],
"target_monthly_rent": spec["target_monthly_rent"],

# 넣는다
"target_purchase_price": spec["target_purchase_price"],
"target_region": spec["target_region"],
```

- [ ] **Step 7: persona_e의 하드코딩 블록을 맞춘다**

`persona_e()`는 스펙 테이블을 쓰지 않고 값을 직접 적어 둔다. 709-716행 부근을 이렇게 바꾼다.

```python
            "target_housing_type": "purchase",
            "target_region": "11650",
            # 서초구 실거래 p05. 설계 문서 3.2의 SQL 참조.
            "target_purchase_price": 325_000_000,
            "target_price": 325_000_000,
            "target_move_in_ym": "202807",
```

633행의 docstring을 바꾼다.

```python
    """E. 대학생1(기본형) — 결과를 미리 정하지 않는 주택 구매 시나리오."""
```

747행 부근의 문구를 바꾼다.

```python
                "상품 평가와 주택 구매 가능성을 확인한다."
```

762-763행(`provided_facts`)과 770행(`generated_assumptions`)의 전월세 키를 지운다.

```python
# provided_facts에서 지운다
"target_lease_deposit": 5_000_000,
"target_monthly_rent": 200_000,

# provided_facts에 넣는다
"target_purchase_price": 325_000_000,

# generated_assumptions에서 지운다
"target_management_fee": 50_000,
```

- [ ] **Step 8: 테스트를 돌려 통과를 확인한다**

Run: `python -m pytest tests/data_pipeline/test_college_student_goals.py -q`
Expected: PASS — 101개 통과 (20 × 5 파라미터 테스트 + 1)

- [ ] **Step 9: 전체 테스트와 린트를 돌린다**

Run: `python -m pytest -q`
Expected: PASS. 매물 픽스처와 서비스를 건드리지 않았으므로 기존 테스트가 전부 통과해야 한다. 하나라도 깨지면 멈추고 원인을 보고한다.

Run: `python -m ruff check app/data_pipeline/mydata/generate_all.py tests/data_pipeline/test_college_student_goals.py`
Expected: PASS

- [ ] **Step 10: 커밋한다**

```bash
git add app/data_pipeline/mydata/generate_all.py tests/data_pipeline/test_college_student_goals.py
git commit -m "feat: 대학생 페르소나 20명의 목표를 매매로 전환

목표가는 각 구의 실거래 p05(전용 85m2 이하, 2025-01-01 이후)를 상수로 박았다.
생성기가 DB에 의존하면 터널이 닫힌 환경에서 픽스처를 만들 수 없다.

affluent 5명은 초기 목표지역도 자산 규모에 맞는 구로 옮겼다. 강남 p05가
3.7억이라 그대로 두면 q 한 명만 통과한다. 재무 값은 한 값도 바꾸지 않았다.

임포트 시점에 sys.argv를 읽던 것도 막았다. pytest로 임포트하면 OUT_ROOT가
pytest의 인자가 된다."
```

---

## Task 2: mydata 산출물을 재생성한다

**Files:**
- Modify: `app/data_pipeline/mydata/persona_*/user_profile.json` (20개 디렉터리)
- Modify: `app/data_pipeline/mydata/persona_*/generation_metadata.json`

**Interfaces:**
- Consumes: Task 1의 `generate_all.py`
- Produces: 각 `persona_*/user_profile.json`이 `target_housing_type: "purchase"`와 새 `target_price`를 담는다. Task 4의 `build-fixtures.mjs`가 이 파일들을 읽는다.

- [ ] **Step 1: 생성기를 돌린다**

```bash
python app/data_pipeline/mydata/generate_all.py
```

Expected: 페르소나 25개(a~d + e + 변형 19)가 출력되고 각각 "파일 N개 거래 M건" 줄이 찍힌다.

- [ ] **Step 2: 산출물을 확인한다**

```bash
python -c "
import json, glob
bad = []
for path in sorted(glob.glob('app/data_pipeline/mydata/persona_*college_student*/user_profile.json')):
    p = json.load(open(path))
    rent = [k for k in ('target_lease_deposit','target_monthly_rent','target_management_fee') if k in p]
    if p['target_housing_type'] != 'purchase' or rent:
        bad.append((path, p['target_housing_type'], rent))
    print(f\"{p['target_region']}  {p['target_price']:>12,}  {path.split('/')[-2]}\")
print('문제:', bad or '없음')
"
```

Expected: 20줄이 찍히고 마지막 줄이 `문제: 없음`. 금액이 Global Constraints의 표와 일치해야 한다.

- [ ] **Step 3: 재무 값이 안 바뀌었는지 확인한다**

```bash
git diff --stat app/data_pipeline/mydata/
git diff app/data_pipeline/mydata/persona_i_college_student_05_basic/user_profile.json
```

Expected: `target_*` 관련 줄만 바뀌어야 한다. `monthly_income`, `monthly_average_expense`, `current_assets`가 diff에 나타나면 **멈추고 보고한다** — 설계 결정 4 위반이다.

거래내역(`bank_004_*.json`)에는 난수 시드가 고정돼 있어(`"seed"`) 변화가 없어야 한다. 변했다면 원인을 확인한 뒤 진행한다.

- [ ] **Step 4: 커밋한다**

```bash
git add app/data_pipeline/mydata/
git commit -m "chore: 매매 목표로 마이데이터 산출물 재생성"
```

---

## Task 3: 웹 계약과 화면 문구를 정리한다

**Files:**
- Modify: `src/lib/contracts/persona.ts:56-61`
- Modify: `src/lib/contracts/persona.test.ts:67-72`
- Modify: `src/lib/format/codes.ts` (`housingTypeLabel`)
- Modify: `src/features/input/step-input.tsx:48`
- Modify: `scripts/build-fixtures.mjs:182-192`

작업 디렉터리는 `housing-finance-web`이다.

**Interfaces:**
- Consumes: Task 2의 `user_profile.json` 형태
- Produces: `personaProfileSchema`의 `goal`이 `target_housing_type`, `target_region`, `target_price`, `target_move_in_ym`, `risk_preference` 다섯 필드만 갖는다. `housingTypeLabel("purchase") === "매매"`.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`src/lib/contracts/persona.test.ts`의 `describe("personaProfileSchema", ...)` 안에 있는 `const valid` 픽스처에서 `goal` 블록을 이렇게 바꾼다(전월세 세 줄 삭제).

```typescript
    goal: {
      target_housing_type: "purchase",
      target_region: "30200",
      target_price: 5000000,
      target_move_in_ym: "202807",
      risk_preference: "stability",
    },
```

그리고 같은 `describe` 블록 안, `"필수 필드가 빠지면 거부한다"` 테스트 **뒤**에 테스트를 추가한다. 픽스처 변수명은 `valid`다.

```typescript
  it("goal에 전월세 필드가 남아 있으면 거부한다", () => {
    const invalid = structuredClone(valid);
    (invalid.goal as Record<string, any>).target_monthly_rent = 200000;
    expect(() => personaProfileSchema.parse(invalid)).toThrow();
  });
```

`src/lib/format/codes.test.ts`에 라벨 테스트를 추가한다.

```typescript
  it("매매 목표를 한국어로 옮긴다", () => {
    expect(housingTypeLabel("purchase")).toBe("매매");
  });
```

- [ ] **Step 2: 테스트를 돌려 실패를 확인한다**

Run: `npm test -- persona codes`
Expected: FAIL — `housingTypeLabel("purchase")`가 `"purchase"`를 그대로 돌려주고(lookup 미스), zod가 여분 필드를 통과시킨다.

> zod 객체는 기본이 strip이라 여분 필드를 조용히 버린다. 테스트가 통과해 버리면
> `goal` 객체에 `.strict()`를 붙여야 한다. 붙일 때는 `personaProfileSchema` 전체가
> 아니라 `goal`에만 붙인다 — 다른 블록까지 엄격해지면 무관한 픽스처가 깨진다.

- [ ] **Step 3: 계약에서 전월세 필드를 뺀다**

`src/lib/contracts/persona.ts`의 `goal` 블록(56-61행 부근)에서 세 줄을 지우고 `.strict()`를 붙인다.

```typescript
  goal: z
    .object({
      target_housing_type: z.string(),
      target_region: z.string(),
      target_price: z.number(),
      target_move_in_ym: z.string().regex(YM),
      risk_preference: z.string(),
    })
    .strict(),
```

- [ ] **Step 4: 라벨을 추가한다**

`src/lib/format/codes.ts`의 `housingTypeLabel` 표에 한 줄을 넣는다. `monthly_rent`는 `current_housing_type`이 계속 쓰므로 **지우지 않는다.**

```typescript
export function housingTypeLabel(code: string): string {
  return lookup(
    {
      purchase: "매매",
      monthly_rent: "월세",
      jeonse: "전세",
      owned: "자가",
      living_with_parents: "부모님과 거주",
      dormitory: "기숙사",
    },
    code,
  );
}
```

- [ ] **Step 5: 픽스처 빌더의 매핑을 고친다**

`scripts/build-fixtures.mjs`의 `goal` 블록(182-192행 부근)에서 세 줄을 지운다.

```javascript
      goal: {
        target_housing_type: userProfile.target_housing_type,
        target_region: userProfile.target_region,
        target_price: userProfile.target_price,
        target_move_in_ym: userProfile.target_move_in_ym,
        risk_preference: userProfile.risk_preference,
      },
```

- [ ] **Step 6: Step 1 화면 설명 문구를 고친다**

`src/features/input/step-input.tsx` 48행의 `description`을 바꾼다.

```tsx
        description="현재 페르소나의 목표 금액은 해당 자치구의 실거래 하위 5% 값입니다. 지역과 금액은 [희망 주택]에서 직접 바꿀 수 있습니다."
```

- [ ] **Step 7: 테스트를 돌려 통과를 확인한다**

Run: `npm test`
Expected: PASS

Run: `npm run typecheck`
Expected: PASS. 실패하면 `goal.target_lease_deposit` 등을 읽는 코드가 남아 있다는 뜻이므로 그 자리를 찾아 지운다.

- [ ] **Step 8: 커밋한다**

```bash
git add src/lib/contracts/persona.ts src/lib/contracts/persona.test.ts \
        src/lib/format/codes.ts src/lib/format/codes.test.ts \
        src/features/input/step-input.tsx scripts/build-fixtures.mjs
git commit -m "feat: 페르소나 계약에서 전월세 목표 필드를 제거한다

goal에 .strict()를 붙였다. zod는 기본이 strip이라 여분 필드를 조용히
버리는데, 그러면 계약에서 뺀 필드가 픽스처에 남아 있어도 아무도 모른다.

housingTypeLabel의 monthly_rent는 남긴다 -- current_housing_type이
계속 쓴다."
```

---

## Task 4: 웹 픽스처를 재빌드한다

**Files:**
- Modify: `src/mocks/fixtures/**` (20개 페르소나 + `index.json`)
- Modify: `public/fixtures/**`

**Interfaces:**
- Consumes: Task 2의 `user_profile.json`, Task 3의 `build-fixtures.mjs`
- Produces: `src/mocks/fixtures/*/profile.json`의 `goal`이 5필드만 갖고 `target_housing_type: "purchase"`를 담는다.

- [ ] **Step 1: 재빌드한다**

```bash
npm run build:fixtures
```

- [ ] **Step 2: 산출물을 확인한다**

```bash
node -e "
const fs = require('fs');
const dirs = fs.readdirSync('src/mocks/fixtures').filter(d => d.startsWith('persona_'));
let bad = [];
for (const d of dirs) {
  const p = JSON.parse(fs.readFileSync(\`src/mocks/fixtures/\${d}/profile.json\`));
  const keys = Object.keys(p.goal).sort().join(',');
  if (p.goal.target_housing_type !== 'purchase') bad.push([d, 'type']);
  if (keys !== 'risk_preference,target_housing_type,target_move_in_ym,target_price,target_region') bad.push([d, keys]);
  console.log(p.goal.target_region, String(p.goal.target_price).padStart(12), d);
}
console.log('문제:', bad.length ? bad : '없음');
"
```

Expected: 20줄 + `문제: 없음`. 금액이 Global Constraints의 표와 일치해야 한다.

- [ ] **Step 3: 전체 테스트를 돌린다**

Run: `npm test`
Expected: PASS

Run: `npm run typecheck`
Expected: PASS

- [ ] **Step 4: 화면에서 육안으로 확인한다**

설계 §3.4의 5번이다. 계약과 테스트가 통과해도 화면 문구가 전월세를 말하고 있을 수 있다.

```bash
npm run dev
```

브라우저에서 `/input?persona=persona_i_college_student_05_basic`을 연다. 다음 네 가지를 확인한다.

1. **Step 1 "목표 설정"** 의 설명 문구가 매매 기준으로 바뀌어 있다
2. **[희망 주택]** 을 눌러 펼친 패널에서 지역이 `영등포구`, 목표 가격이 `300,000,000`이다
3. **Step 3 "입력 확인"** 의 "목표 가격"이 3억원으로 표시된다
4. 화면 어디에도 "월세", "보증금", "관리비"가 남아 있지 않다

하나라도 어긋나면 원인을 고친 뒤 Step 3의 테스트를 다시 돌린다.

- [ ] **Step 5: 커밋한다**

```bash
git add src/mocks/fixtures public/fixtures
git commit -m "chore: 매매 목표로 웹 픽스처 재빌드"
```

---

## Task 5: 엔진으로 판정을 재확인하고 설계 문서에 반영한다

**Files:**
- Create: `scripts/check_persona_affordability.py` (core, 읽기 전용 확인 도구)
- Modify: `docs/superpowers/specs/2026-08-01-persona-home-purchase-design.md` (2.3 표와 5장)

작업 디렉터리는 `housing-finance-core`다.

**Interfaces:**
- Consumes: Task 2의 산출물
- Produces: 실제 판정 인원수. 설계 문서 2.3·5장의 "가능 3명"을 실측으로 대체한다.

**왜 필요한가:** 설계 2.3의 "가능 3명"은 LTV 70%와 DSR 40%만 본 손계산이다. **스트레스 가산금리·상품별 한도·Rule Pack 자격을 반영하지 않았다.** 심사는 '실제 금리 + 스트레스 가산금리'로 하므로 실제 한도는 더 낮고, 통과 인원이 3명보다 줄 수 있다. 확정 사실처럼 문서에 남겨두면 안 된다.

- [ ] **Step 1: 확인 스크립트를 만든다**

`scripts/check_persona_affordability.py`를 만든다.

```python
#!/usr/bin/env python
"""페르소나별 구매 가능성을 엔진으로 판정한다(읽기 전용).

    python scripts/check_persona_affordability.py

설계 문서 2.3의 손계산은 LTV·DSR만 본 근사다. 스트레스 가산금리와 Rule Pack
자격을 반영한 실제 판정을 확인해 문서에 반영하기 위한 도구다.
"""

import glob
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from app.regulations.mortgage_limits import HousingStatus
from app.schemas.simulation import (
    FinancialSnapshot,
    HousingGoal,
    LoanRequestInput,
    SimulationInput,
    UserProfile,
)
from app.services.loan_product_catalog import load_configured_loan_candidates
from app.services.simulation_orchestrator import run_simulation

AS_OF = date(2026, 8, 1)
MYDATA = os.path.join("app", "data_pipeline", "mydata")


def build_input(profile: dict) -> SimulationInput:
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
            target_date=date(2028, 7, 1),
            region_code=profile["target_region"],
        ),
        financial_snapshot=FinancialSnapshot(
            monthly_income=Decimal(profile["monthly_income"]),
            monthly_expense=Decimal(profile["monthly_average_expense"]),
            liquid_assets=Decimal(profile.get("current_assets", 0)),
            monthly_debt_payment=Decimal(profile.get("monthly_debt_payment", 0)),
        ),
        loan_request=LoanRequestInput(
            months=360,
            housing_status=HousingStatus.FIRST_HOME_BUYER,
            monthly_essential_expense=Decimal(profile["monthly_average_expense"]),
        ),
    )


def main() -> int:
    candidates = load_configured_loan_candidates(as_of=AS_OF)
    rows = []
    for path in sorted(glob.glob(f"{MYDATA}/persona_*college_student*/user_profile.json")):
        directory = os.path.dirname(path)
        profile = json.load(open(path, encoding="utf-8"))
        result = run_simulation(
            build_input(profile),
            simulation_id=uuid4(),
            as_of=AS_OF,
            calculated_at=datetime.now(tz=UTC),
            loan_candidates=candidates,
        )
        loan = result.loan_simulation
        status = loan.engine_status or loan.run_status.value
        # 부족액이 0이거나 없으면 조달된 것으로 본다. form.py의 5절이 읽는 것과
        # 같은 키다(`_shortfall_and_extension`).
        facts = loan.result or {}
        shortfall = facts.get("funding_shortfall")
        rows.append(
            (os.path.basename(directory), profile["target_price"], status, shortfall)
        )

    print(f"{'페르소나':44}{'목표가':>14}{'부족액':>16}  상태")
    buyable = 0
    for name, price, status, shortfall in rows:
        ok = shortfall is not None and Decimal(str(shortfall)) <= 0
        buyable += ok
        text = "없음" if ok else ("확인불가" if shortfall is None else f"{Decimal(str(shortfall)):,}")
        print(f"{name:44}{price:>14,}{text:>16}  {status}")
    print(f"\n구매 가능 {buyable}명 / 미달·확인불가 {len(rows) - buyable}명")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 스크립트를 돌린다**

Run: `python scripts/check_persona_affordability.py`
Expected: 20줄이 찍힌다.

대출 상품 카탈로그가 없어 503이 나면(`LoanProductCatalogUnavailable`) DB 터널이 필요하다. 터널을 열 수 없으면 **여기서 멈추고 보고한다.** 값을 추정해 문서에 적지 않는다.

- [ ] **Step 3: 판정 인원을 확인한다**

스크립트 마지막 줄의 `구매 가능 N명 / 미달·확인불가 M명`을 읽는다.

`확인불가`(부족액 키가 없음)가 섞여 있으면 그 페르소나의 대출 구간이 실행되지 않은 것이다. `상태` 열과 `loan.missing_inputs`를 확인해 원인을 찾는다. **`확인불가`를 `미달`로 뭉개서 세지 않는다** — 계산하지 못한 것과 계산해 보니 부족한 것은 다른 상태다(§22.1).

- [ ] **Step 4: 설계 문서를 실측으로 고친다**

`docs/superpowers/specs/2026-08-01-persona-home-purchase-design.md`에서 두 곳을 고친다.

1. **2.3의 표** — "판정" 열을 손계산이 아니라 엔진 결과로 바꾸고, 표 아래 문단의 "다만 이 검산은 ... 확인해야 한다"를 실행 결과 서술로 교체한다.
2. **5장 첫 문장** — "3명 / 미달 17명(§3.4의 4번에서 엔진으로 재확인 필요)"을 실측 숫자로 바꾸고 괄호를 지운다.

손계산과 실측이 다르면 **그 차이와 원인(스트레스 가산금리 등)을 문서에 남긴다.** 조용히 숫자만 갈아끼우지 않는다.

- [ ] **Step 5: 린트를 돌리고 커밋한다**

Run: `python -m ruff check scripts/check_persona_affordability.py`
Expected: PASS

```bash
git add scripts/check_persona_affordability.py docs/superpowers/specs/2026-08-01-persona-home-purchase-design.md
git commit -m "test: 엔진으로 페르소나 구매 가능성을 재확인하고 설계에 실측 반영

2.3의 '가능 3명'은 LTV·DSR만 본 손계산이었다. 스트레스 가산금리와 Rule Pack
자격을 반영한 실제 판정으로 교체한다."
```

---

## 완료 조건

- [ ] core `python -m pytest -q` 전부 통과
- [ ] web `npm test`, `npm run typecheck` 전부 통과
- [ ] 20명 프로필의 `target_housing_type`이 `"purchase"`이고 전월세 3필드가 없다
- [ ] 20명의 `target_price`가 Global Constraints의 표와 일치한다
- [ ] 페르소나의 소득·지출·자산·저축이 한 값도 바뀌지 않았다
- [ ] 설계 문서의 판정 인원이 손계산이 아니라 엔진 실측이다
