# Calculation engines

각 엔진은 같은 입력에 항상 같은 결과를 반환하는 결정론적 코드로 작성합니다.

- `cashflow/`: 안전소득·생활비·잉여현금·비상자금
- `loan/`: 대출 가능액·원리금·DSR·상품 비교
- `savings/`: 예상 실효금리·상품 평가·포트폴리오
- `recommendation/`: 대출과 예적금 결과의 종합추천
- `stress/`: 금리·소득·생활비 충격
- `strategy/`: 자산축적형과 조기구매형 비교

AI는 계산값을 변경하지 않고 `reports/`에서 설명만 생성합니다.

