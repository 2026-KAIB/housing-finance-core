# 종합추천 엔진 계약

## 목적

상품 Rule Pack, 대출 시뮬레이션, 예·적금 평가·포트폴리오가 만든 결과를
다시 해석하거나 수정하지 않고 하나의 결정론적 추천 결과로 합친다. AI는 이
결과를 설명할 수만 있으며 금액·점수·순위를 변경할 수 없다.

## 계층 경계

```text
LoanSimulationResult ─┐
                      ├─ services/recommendation.py
SavingsPortfolioResult│        │
최종 정책 재검증 ─────┘        ▼
                         CombinedRecommendationInput
                                  │
                                  ▼
                         engines/recommendation
                                  │
                                  ▼
                         CombinedRecommendationResult
```

- `models.py`: 순수 엔진 입출력과 서비스 내부 추천정책을 정의한다.
- `engine.py`: 동일 금액·동일 기간 대출 비교, 예·적금 정책검증 게이트,
  종합 상태 결정을 수행한다.
- `services/recommendation.py`: 다른 계층의 객체를 입력 계약으로 변환한다.
- 엔진은 DB, FastAPI, 원천 상품 데이터, Rule Pack 레지스트리를 직접 호출하지 않는다.

## 대출 점수

공식 설계안 §14의 가중치를 기본값으로 사용한다.

```text
대출점수
= 100 × (
    0.30 × 상환가능성
  + 0.25 × 총비용
  + 0.20 × 위기대응력
  + 0.15 × 금리안정성
  + 0.10 × 상환유연성
)
```

필수조건과 대출 안전한도를 통과해 `LoanSimulationResult.executable`에 들어온
후보만 점수화한다. 추천금액은 `min(필요금액, 계산된 최대 가능액)`이며 계산된
한도를 늘리지 않는다.

현재 상품 DB에는 보증료·인지비용 등 추가 금융비용과 상환유연성의 구조화 값이
완전하지 않다. 이 값을 0점 또는 0원으로 만들지 않는다. 확인된 점수 가중치가
정책 임계 이상이면 `PROVISIONAL`, 부족하면 `UNAVAILABLE`로 반환하고
`missing_score_components`에 결측 항목을 남긴다.

## 예·적금 게이트

예·적금 포트폴리오가 계산됐더라도
`revalidate_savings_portfolio_policy()`의 최종 판정이 `PASS`가 아니면
배분 상품을 종합추천으로 전달하지 않는다.

- `PASS`: `COMPLETE` 또는 `PARTIAL` 배분안을 전달
- `UNKNOWN`: 배분안을 숨기지 않고 결측 사유를 반환하되 추천 목록에는 넣지 않음
- `FAIL`: 정책을 위반한 배분안을 추천에서 제외

## 결과 상태

- `COMPLETE`: 요청된 모든 구성요소가 확정됨
- `PARTIAL`: 사용할 수 있는 결과는 있으나 일부 금액·예산이 미충족
- `NEEDS_REVIEW`: 입력 결측, 정책 UNKNOWN, 임시 점수 또는 한도 가정이 있음
- `INFEASIBLE`: 확정된 입력으로 실행 가능한 결과가 없음

이 상태는 금융기관의 승인 여부가 아니라 **종합추천 결과의 완성도**다.

## 아직 필요한 데이터

완전한 대출점수를 만들려면 상품별로 다음 값을 구조화해야 한다.

- 보증료, 인지·설정비용, 기타 수수료, 정책·우대 혜택
- 중도상환수수료와 적용기간
- 거치기간, 금리전환, 대환·추가상환 가능 여부

값이 마련되면 `LoanRecommendationSupplement`로 서비스 조립 계층에 공급할 수
있으며 순수 추천엔진이나 대출 계산엔진은 수정하지 않아도 된다.
