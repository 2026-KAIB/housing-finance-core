# Housing Finance Core

주택구매 금융 컨설팅 서비스의 백엔드, 데이터 파이프라인, 금융 계산 엔진을 한곳에서 관리합니다.

## 담당 영역

- FastAPI와 공용 입출력 계약
- 개인 금융데이터 수집·검증·정규화
- 상품·정책·부동산 기준데이터 수집과 버전 관리
- 정책·상품 Rule Engine
- 대출·DSR 엔진
- 예적금 평가·포트폴리오 엔진
- 종합추천·스트레스 테스트·전략 비교
- AI 설명과 보고서 검증

## 로컬 실행

Python 3.12 이상을 권장합니다.

```powershell
source .venv/bin/activate
uvicorn app.main:app --reload
```

API 문서:

- Swagger UI: http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

## 테스트

```powershell
pytest
ruff check .
```

## 모듈 경계

```text
app/
├─ api/              FastAPI 라우터
├─ core/             환경설정과 공통 기반 코드
├─ schemas/          SimulationInput/Result 등 공용 계약
├─ data_pipeline/    수집·검증·정규화·적재
├─ rule_engine/      정책·대출·예적금 자격 규칙
├─ engines/          금융 계산과 종합추천
├─ reports/          보고서 템플릿·AI 설명·검증
└─ db/               DB 세션·모델·저장소
```

원본 대용량 데이터와 실제 개인정보는 Git에 커밋하지 않습니다. `sample_data/`에는 테스트용 가상 데이터만 저장합니다.
