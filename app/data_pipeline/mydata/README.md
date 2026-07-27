# Mock 데이터 생성 결과 설명

이 문서는 generate_all.py를 실행했을 때 생성되는 합성 금융 데이터의 구조와 의미를 정리한 GitHub 업로드용 README입니다.

## 1. 개요

`generate_all.py`를 실행하면 기존 주택금융 페르소나 4명과 대학생 페르소나
20명, 총 24개의 페르소나별 폴더가 생성됩니다.

- `persona_a_social_starter`
- `persona_b_newlywed_jeonse`
- `persona_c_dual_income_mortgage`
- `persona_d_credit_line`
- `persona_e_college_student_basic`부터
  `persona_x_college_student_20_poor`까지의 대학생 20명

대학생 20명의 유형과 인물 설명은
[`college_student_personas.md`](college_student_personas.md)에 정리되어 있습니다.

각 폴더에는 해당 페르소나의 은행 계좌, 예적금, 대출, 거래내역, 사용자 프로필 정보가 JSON 형태로 저장됩니다.

이 데이터는 실제 금융API 응답 형식과 유사한 구조를 가진 가상 데이터이며, 계산 엔진에서 월 상환액·DSR·가용자산 등을 별도로 산출하는 방식으로 구성되어 있습니다.

---

## 2. 실행 방법

```bash
python3 generate_all.py
```

기본적으로 현재 폴더 아래에 결과물이 생성됩니다.

```bash
python3 generate_all.py /path/to/output_dir
```

위 명령처럼 출력 디렉토리를 직접 지정할 수도 있습니다.

---

## 3. 생성되는 폴더 구조

실행 결과는 아래와 같은 구조로 생성됩니다.

```text
output_dir/
├── persona_a_social_starter/
│   ├── bank_001_accounts.json
│   ├── bank_002_deposit_basic_10120304000001.json
│   ├── bank_003_deposit_detail_10120304000001.json
│   ├── bank_004_deposit_trans_10120304000001.json
│   ├── bank_008_loan_basic_10120304000003.json
│   ├── bank_009_loan_detail_10120304000003.json
│   └── user_profile.json
├── persona_b_newlywed_jeonse/
│   ├── bank_001_accounts.json
│   ├── bank_002_deposit_basic_20230815000001.json
│   ├── bank_003_deposit_detail_20230815000001.json
│   ├── bank_004_deposit_trans_20230815000001.json
│   ├── bank_008_loan_basic_20230815000004.json
│   ├── bank_009_loan_detail_20230815000004.json
│   └── user_profile.json
├── persona_c_dual_income_mortgage/
│   ├── bank_001_accounts.json
│   ├── bank_002_deposit_basic_11020204000001.json
│   ├── bank_003_deposit_detail_11020204000001.json
│   ├── bank_004_deposit_trans_11020204000001.json
│   ├── bank_008_loan_basic_11020204000005.json
│   ├── bank_009_loan_detail_11020204000005.json
│   └── user_profile.json
├── persona_d_credit_line/
│   ├── bank_001_accounts.json
│   ├── bank_002_deposit_basic_30200210000001.json
│   ├── bank_003_deposit_detail_30200210000001.json
│   ├── bank_004_deposit_trans_30200210000001.json
│   ├── bank_008_loan_basic_30200210000004.json
│   ├── bank_009_loan_detail_30200210000004.json
│   └── user_profile.json
└── persona_e_college_student_basic/
    ├── bank_001_accounts.json
    ├── bank_002_deposit_basic_40100102000001.json
    ├── bank_003_deposit_detail_40100102000001.json
    ├── bank_004_deposit_trans_40100102000001.json
    ├── user_profile.json
    ├── savings_preferences.json
    └── generation_metadata.json
```

---

## 4. 파일별 의미

각 폴더 안의 파일은 다음 역할을 합니다.

| 파일명 | 설명 |
|---|---|
| `bank_001_accounts.json` | 계좌 목록 정보 |
| `bank_002_deposit_basic_*.json` | 예적금 기본 정보 |
| `bank_003_deposit_detail_*.json` | 예적금 상세 정보 |
| `bank_004_deposit_trans_*.json` | 거래내역 정보 |
| `bank_008_loan_basic_*.json` | 대출 기본 정보 |
| `bank_009_loan_detail_*.json` | 대출 상세 정보 |
| `user_profile.json` | 사용자 프로필 및 생활 패턴 정보 |
| `savings_preferences.json` | 예적금 평가에 필요한 예산·목표일·사용자 선호 입력 |
| `generation_metadata.json` | 사용자가 준 사실과 자동 생성한 가정을 분리한 생성 근거 |

각 파일은 실제 금융 API 응답 형식에 맞춰 설계된 JSON 구조를 사용합니다.

---

## 5. 포함되는 시나리오

생성되는 데이터는 다음 4가지 시나리오를 기반으로 합니다.

1. `persona_a_social_starter`
   - 사회초년생
   - 월세 거주
   - 학자금대출 보유
   - 청약 저축 보유

2. `persona_b_newlywed_jeonse`
   - 신혼부부
   - 전세 거주
   - 전세자금대출 보유
   - 부부 소득 합산 시나리오

3. `persona_c_dual_income_mortgage`
   - 맞벌이
   - 기존 주담대 보유
   - 복수 대출 상황
   - 거치식 대출 포함

4. `persona_d_credit_line`
   - 마이너스통장 보유
   - 자동차 할부 대출
   - 변동 소득 및 부채 관리 시나리오

5. 대학생 페르소나 20명
   - 기본형 7명, 부유형 6명, 가난형 7명
   - 소득·지출·자산·학자금대출·주거형태와 월세 목표를 서로 다르게 구성
   - 기대 결과를 미리 지정하지 않고 엔진 결과를 관찰하는 시나리오

---

## 6. 검증 방법

생성 후 데이터의 정합성을 확인하려면 아래 명령을 실행합니다.

```bash
python3 validate_all.py <출력디렉토리>
```

이 검증 스크립트는 거래내역 잔액, 대출 상환 정보, 계좌 연결 관계 등을 확인합니다.

---

## 7. 실제 상품 DB로 대학생 포트폴리오 테스트

`run_college_student_portfolios.py`는 대학생 20명의 합성 MyData와 실제 상품
DB를 연결해 아래 계층을 순서대로 통합 검증합니다.

```text
상품 DB 조회(읽기 전용)
→ 상품 Rule Pack
→ 예적금 계산 입력 변환 및 계산
→ 상품 옵션 평가
→ 포트폴리오 배분
→ 선택 상품 Rule Pack 최종 재검증
```

DB 포트를 직접 외부에 열지 않고 SSH 터널을 먼저 생성합니다.

```bash
ssh -N -L 15432:127.0.0.1:5432 \
  -p <SSH_PORT> <SSH_USER>@<HOME_SERVER_IP>
```

프로젝트 루트의 다른 터미널에서 실행합니다.

```bash
python -m app.data_pipeline.mydata.run_college_student_portfolios \
  --db-host 127.0.0.1 \
  --db-port 15432 \
  --db-user <DB_USER> \
  --db-name <DB_NAME>
```

DB 비밀번호는 프롬프트로만 입력하며 코드·명령행·결과 파일에 저장하지 않습니다.
DB 연결은 읽기 전용 트랜잭션으로 설정됩니다. 실행 결과는 다음 파일에 기록됩니다.

- `college_student_portfolio_results.json`: 계층별 원본 판정과 포트폴리오 수치
- `college_student_portfolio_results.md`: 사람별 요약 및 판정 사유

현재 저장된 결과는 2026-07-28 기준 스냅샷입니다. 상품 DB나 정책 팩이 바뀌면
동일 명령으로 다시 생성해야 합니다.

---

## 8. 참고

- 생성되는 데이터는 모두 합성 데이터입니다.
- 실제 금융기관의 실 데이터가 아닙니다.
- 계산 결과(월 상환액, DSR, 가용자산 등)는 본 문서에 포함되지 않으며, 별도 계산 엔진에서 산출하는 구조입니다.
