# Mock 데이터 생성 결과 설명

이 문서는 generate_all.py를 실행했을 때 생성되는 합성 금융 데이터의 구조와 의미를 정리한 GitHub 업로드용 README입니다.

## 1. 개요

`generate_all.py`를 실행하면 다음 4개의 페르소나별 폴더가 생성됩니다.

- `persona_a_social_starter`
- `persona_b_newlywed_jeonse`
- `persona_c_dual_income_mortgage`
- `persona_d_credit_line`

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
└── persona_d_credit_line/
    ├── bank_001_accounts.json
    ├── bank_002_deposit_basic_30200210000001.json
    ├── bank_003_deposit_detail_30200210000001.json
    ├── bank_004_deposit_trans_30200210000001.json
    ├── bank_008_loan_basic_30200210000004.json
    ├── bank_009_loan_detail_30200210000004.json
    └── user_profile.json
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

---

## 6. 검증 방법

생성 후 데이터의 정합성을 확인하려면 아래 명령을 실행합니다.

```bash
python3 validate_all.py <출력디렉토리>
```

이 검증 스크립트는 거래내역 잔액, 대출 상환 정보, 계좌 연결 관계 등을 확인합니다.

---

## 7. 참고

- 생성되는 데이터는 모두 합성 데이터입니다.
- 실제 금융기관의 실 데이터가 아닙니다.
- 계산 결과(월 상환액, DSR, 가용자산 등)는 본 문서에 포함되지 않으며, 별도 계산 엔진에서 산출하는 구조입니다.
