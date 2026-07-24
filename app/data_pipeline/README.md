# Data pipeline

담당자 1의 기본 작업 공간입니다.

```text
collectors/   외부 상품·정책·부동산 데이터 수집
adapters/     JSON·CSV·향후 마이데이터 공급자 변환
validators/   스키마·금액·날짜·필수값 검증
normalizers/  내부 표준 모델과 단위로 변환
cleaners/     중복·누락·이상값 처리
loaders/      PostgreSQL 적재와 기준일·출처 버전 기록
mydata/       합성 마이데이터 생성(generate_all.py) 및 검증(validate_all.py)
```

최종 출력은 엔진이 바로 소비할 수 있는 정규화 모델이어야 합니다. 원본 데이터의 차이는 Adapter와 Normalizer에서 흡수합니다.

