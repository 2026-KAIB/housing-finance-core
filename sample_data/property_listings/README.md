# 매물 JSON 계약 v1

이 폴더의 데이터는 실제 매물이 아닌 개발·테스트용 완전 가상 데이터다.
지금은 JSON 저장소가 읽고, DB 정규화가 완료되면 동일한
`PropertyListingRepository` 인터페이스를 구현한 DB 저장소로 교체한다.

## 파일

- `property_listings.v1.json`: 검색 서비스가 읽는 매물 스냅샷
- `property_search_cases.v1.json`: 프론트 입력 조건과 기대 검색 결과 예시

## 단위와 규칙

- 금액: 원(`price_krw`), JSON에서는 정밀도 보존을 위해 문자열 사용
- 면적: 제곱미터(`exclusive_area_m2`)
- 거리: 미터(`distance_m`)
- 도보 시간: 분(`walk_minutes`)
- 행정구역 코드: 시도 2자리, 시군구 5자리, 법정동 10자리
- 시간: 타임존이 포함된 ISO 8601, 알 수 없는 매물 시각은 `null`
- 알 수 없는 값은 임의로 0을 넣지 않고 `null` 또는 빈 배열 사용
- 검색 대상은 `ACTIVE` 상태이며 요청한 거래 유형과 일치하는 매물만 포함
- 역세권 조건이 켜져 있는데 역 정보가 없으면 해당 매물은 검색에서 제외

## DB 담당자에게 필요한 매핑

DB 저장소는 `search_candidates(criteria)`에서 지역·금액 등의 1차 조건으로
행을 좁힌 뒤 `PropertyListingDataset`을 반환하면 된다. 검색 서비스가 동일 조건을
다시 적용하므로 JSON과 DB의 최종 판정 규칙은 같다. 검색 서비스와 금융 엔진은
JSON인지 DB인지 알 필요가 없다. 외부 공급자의 식별자는 `source_listing_id`,
우리 서비스 내부 식별자는 `listing_id`로 분리하며 두 식별자의 중복을 허용하지
않는다.
