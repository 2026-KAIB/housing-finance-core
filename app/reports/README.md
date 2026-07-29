# Reports

1. 계산 엔진이 `SimulationResult`를 생성합니다.
2. 고정 템플릿이 AI 없이도 기본 보고서를 만듭니다.
3. AI는 제공된 계산 결과만 사용해 설명을 생성합니다.
4. 검증기가 금액·상품명·정책 버전을 다시 확인합니다.
5. 웹 보고서와 PDF·Markdown 출력을 생성합니다.

AI 호출 실패 시에도 고정 템플릿 결과는 제공되어야 합니다.

## AI 입력 경계

`SimulationResult`는 프론트엔드·DB·보고서가 공유하는 전체 계산 원본이다.
`reports/context.py`는 이 원본에서 개인정보와 불필요한 하위 계산을 제거한
`ReportAIInput`을 만든다. AI에는 원천 마이데이터를 직접 전달하지 않는다.

```text
SimulationResult
      │
      ├─ 고정 템플릿 보고서
      └─ build_report_ai_input()
                  │
                  ▼
           ReportAIInput JSON
                  │
                  ▼
             AI 설명 생성
```

AI가 반환한 설명은 숫자·상품명·정책 버전 검증을 통과한 뒤에만 최종 보고서에
합친다. 계산 결과와 AI 문장은 별도 필드로 보존한다.
