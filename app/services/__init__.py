"""엔진·규제표·Rule Pack을 하나의 요청 흐름으로 조립하는 계층.

엔진(`app/engines`)은 순수 계산, 규제표(`app/regulations`)는 순수 상수,
Rule Pack(`app/rule_engine`)은 순수 판정이다. 이들을 실제 사용자 요청 하나로
엮는 순서와 결측 처리 규약이 여기 있다. API 라우트는 이 계층만 호출한다.
"""
