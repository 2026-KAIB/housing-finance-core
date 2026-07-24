# 상품별 Rule Pack 개발 가이드

이 디렉터리는 DB 구조를 가정하지 않고, 제한된 상품의 자유 텍스트 조건을
검수된 코드 규칙으로 옮겨 실행하는 계층이다.

## 디렉터리 역할

```text
product_packs/
├─ models.py              공용 요청·결과·상태·Pack 계약
├─ rules.py               단순 비교와 상품 고유 조건 도구
├─ registry.py            상품명·별칭·기준일로 Pack 선택
├─ engine.py              모든 상품이 공유하는 단일 판정기
├─ handoff.py             상품·옵션·사용자 정보에 판정 결과를 붙여 전달
└─ packs/
   ├─ __init__.py         실제 서비스에 사용할 Pack 등록 목록
   ├─ example_product.py  복사 전용 예제, 서비스에는 미등록
   └─ <상품별 파일>.py     앞으로 추가할 24개 상품 Pack
```

## 상품 하나 추가하기

1. `packs/example_product.py`를 복사해 상품별 파일을 만든다.
2. 공식 상품명, 정확한 별칭, 카테고리, 적용기간, 버전, 근거 URL을 기록한다.
3. 단일 필드 비교는 `ComparisonRule`로 작성한다.
4. AND·OR·예외·여러 필드 계산은 `PredicateRule` 함수로 작성한다.
5. 알 수 없는 값이나 해석하지 못한 조건은 함수에서 `None`을 반환한다.
6. 경계값, 실패, 결측값 테스트를 작성한다.
7. 동료 검수 후 `packs/__init__.py`의 `PRODUCT_RULE_PACKS`에 등록한다.

파일명은 영문 `snake_case`를 사용한다. 상품 조회는 공식 상품명 완전일치를
기본으로 하며, 띄어쓰기 변형이나 과거 명칭은 `aliases`에 명시한다. 오타를
임의로 유사 검색하지 않는 이유는 잘못된 상품 Pack 선택을 방지하기 위해서다.

## 입력값 규칙

`ProductEvaluationRequest.facts`는 정규화된 이름-값 사전이다. 현재는 DB나 API
스키마와 연결하지 않는다. 팀에서 사용하는 필드 이름은 상품 Pack끼리 통일한다.

```python
request = ProductEvaluationRequest(
    product_name="정확한 상품명",
    as_of=date(2026, 7, 24),
    facts={
        "age": 32,
        "annual_income": 45_000_000,
        "employment_months": 20,
    },
)
result = evaluate_product(request)
```

한 상품 안의 모든 규칙은 기본적으로 AND로 취합한다.

- 하나라도 `FAIL`이면 최종 `FAIL`
- `FAIL` 없이 하나라도 `UNKNOWN`이면 최종 `UNKNOWN`
- 모두 `PASS`이면 최종 `PASS`

## 자유 텍스트를 옮기는 원칙

- 원문 의미를 추측해 수치나 조건을 만들지 않는다.
- `그리고`는 AND, `또는`은 OR인지 공식 문서 문맥으로 확인한다.
- 우대금리 조건과 가입 가능 조건을 섞지 않는다.
- 내부 추천 기준과 실제 가입 제한 조건을 섞지 않는다.
- 조건의 근거 URL과 확인일을 Pack 버전에 남긴다.
- RAG가 추출한 조건은 초안으로만 사용하고 사람의 검수 후 등록한다.

## 기존 Rule Engine과 관계

기존 `policy/`, `loans/`, `savings/`는 그대로 유지한다. 신규 서비스는 우선
`product_packs.evaluate_product()`를 상품 조건 판정 진입점으로 사용한다.
기존 계산 로직에서 재사용할 가치가 있는 규칙은 추후 공통 Rule로 옮길 수 있다.

## 다음 예적금·대출 엔진으로 전달하기

Rule Pack은 상품 가입 필수조건만 판정하므로 상품 기본정보와 `optionList`를
직접 소유하지 않는다. 상위 서비스는 원본 데이터를 `ProductCandidate`에 담고
`route_product_candidates()`를 호출한다.

```python
candidate = ProductCandidate(
    product_name=raw_product["baseList"]["fin_prdt_nm"],
    base_data=raw_product["baseList"],
    option_list=tuple(raw_product["optionList"]),
)
result = route_product_candidates(
    [candidate],
    user_facts={
        "deposit_amount": 10_000_000,
        "applicant_type": "individual",
    },
    as_of=date(2026, 7, 24),
)
```

결과는 다음 세 갈래로 분리된다.

- `forwardable`: 모든 가입 필수조건을 통과해 다음 계산 엔진으로 전달
- `rejected`: 가입 필수조건을 명확히 충족하지 못해 제외
- `needs_review`: 입력이나 원문이 부족해 판정을 확정하지 못함

각 결과에는 `product.base_data`, `product.option_list`, `user_facts`,
`rule_result`가 함께 들어 있다. 예적금 엔진은 `forwardable`의 옵션별 금리와
우대조건을 계산하고, 대출 엔진은 옵션별 한도·금리·상환방식을 계산한다.
