# SimulationResult JSON 계약

## 목적

각 계산 엔진은 정밀한 `Decimal`, `date`, enum, 불변 dataclass를 유지한다.
API·프론트엔드·DB·보고서 AI는 엔진 객체를 직접 소비하지 않고 버전형
`SimulationResult` JSON을 공통 원본으로 사용한다.

```text
CashflowResult ───────────┐
SavingsPortfolioResult ──┤
LoanSimulationResult ────┤
RecommendationResult ────┼─ services/simulation_result.py
StressTestResult ─────────┤                 │
StrategyComparisonResult ┘                 ▼
                                  SimulationResult v1
                                            │
                         ┌──────────────────┼────────────────┐
                         ▼                  ▼                ▼
                    Frontend/PDF        DB JSONB      ReportAIInput
```

## 직렬화 규칙

- `Decimal`: JSON 문자열
- `date`, `datetime`: ISO 8601 문자열
- enum: enum 값
- tuple: JSON 배열
- 미확정값: `null`
- 미실행 엔진: `run_status=NOT_RUN`, `result=null`
- 실행 완료 엔진: `run_status=COMPLETED`
- `UNKNOWN`, `FAIL`, `NOT_RUN`은 서로 다른 의미이므로 합치지 않는다.
- 알 수 없는 Python 객체를 임의 문자열로 바꾸지 않고 변환 오류로 처리한다.

각 계산 구간은 자체 `section_schema_version`을 갖는다. 일부 엔진의 출력만 바뀔 때
전체 계약 버전을 즉시 올리지 않고 해당 구간 소비자가 변경을 감지할 수 있다.

## 보고서 AI 입력

`reports/context.py`는 전체 결과에서 AI에 필요한 사실만 골라
`ReportAIInput`을 만든다.

- 종합추천이 있으면 정책검증이 끝난 대출·예적금 요약을 우선한다.
- 계좌번호, 인증정보, 원천 거래목록은 재귀적으로 제거한다.
- AI는 숫자·상품명·상태를 재계산하거나 변경할 수 없다.
- AI 호출에 실패해도 `SimulationResult`와 고정 템플릿 보고서는 유지된다.

## 변경 원칙

기존 필드 의미를 바꾸거나 삭제하면 `schema_version`을 올린다. 선택 필드 추가처럼
하위 호환되는 변경은 해당 구간 버전을 올리고 JSON 계약 테스트를 갱신한다.
