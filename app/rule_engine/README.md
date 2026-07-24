# Rule Engine

정책·상품의 필수조건을 점수 계산보다 먼저 판정합니다.

- `product_packs/`: 제한된 상품을 상품명별 Rule Pack으로 판정하는 신규 진입점
- `common/`: 기존 공통 결정 모델과 규칙 조합
- `policy/`: 기존 정책 적용기간, 소득·연령·지역 등의 조건
- `loans/`: 기존 LTV·DTI·DSR 및 대출상품 자격 조건
- `savings/`: 기존 예적금 가입조건, 납입한도, 우대조건

모든 결정에는 규칙 코드, 통과 여부, 근거 문장, 사용한 데이터 버전을 남깁니다.

신규 상품 개발은
[`product_packs/README.md`](product_packs/README.md)의 절차를 따릅니다. 상품별
차이는 `packs/`에 두고 실행·결과 취합 방식은 공통 엔진 하나로 유지합니다.
