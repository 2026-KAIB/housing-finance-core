# 로컬 개발용 DB 터널

운영에서는 FastAPI와 PostgreSQL이 같은 Docker 네트워크에 있어(`postgres:5432`)
터널이 필요 없다. 이 문서는 **개발자 로컬에서만** 해당한다.

## 왜 앱이 터널을 열지 않는가

1. 운영 경로에서 한 번도 실행되지 않는 코드가 앱에 상주한다.
2. root SSH 자격증명이 애플리케이션 환경변수로 들어간다 — DB 계정보다 훨씬 강한 권한이다.
3. 재접속·헬스체크 같은 터널 생명주기를 앱이 떠안는다.

터널은 개발 도구이지 애플리케이션의 일부가 아니다.

## 여는 법

별도 터미널에서 실행하고, 개발하는 동안 창을 열어 둔다.

```bash
ssh -p <SSH_PORT> -L 15432:localhost:5432 <USER>@<HOST>
```

접속 대상 값은 이 문서에 적지 않는다. 팀에서 따로 전달받아 `.env`에만 둔다.

로컬 `5432`가 아니라 **`15432`로 받는다.** 로컬에 다른 PostgreSQL이 떠 있으면
같은 포트로 받았을 때, 터널이 열리지 않은 상태에서도 조용히 로컬 DB에 붙는다.
그러면 "연결은 되는데 테이블이 없다"는 원인을 찾기 어려운 실패가 난다.

## `.env`

`.env`는 git이 추적하지 않는다(`.gitignore`). 실제 값은 여기에만 둔다.

```dotenv
DATABASE_HOST=localhost
DATABASE_PORT=15432
DATABASE_NAME=<DB 이름>
DATABASE_USER=<계정>
DATABASE_PASSWORD=<비밀번호>
REGION_PRICE_PROVIDER=database
```

`DATABASE_PASSWORD`는 `SecretStr`로 읽으므로(`app/core/config.py`) 로그와
예외 메시지에 값이 찍히지 않는다. 특수문자가 있어도 URL 인코딩은 필요 없다 —
`build_database_url()`이 문자열을 잇지 않고 필드로 넘긴다.

## 확인

```bash
pg_isready -h localhost -p 15432
python scripts/check_region_price_db.py 11680
```

터널이 닫혀 있으면 `pg_isready`가 `no response`를 낸다.
점검 스크립트는 읽기 전용이며, 실제 테이블이 `db_schema_realestate.md`와
일치하는지 컬럼 단위로 대조한다.

## 자주 겪는 실패

| 증상 | 원인 |
|---|---|
| `pg_isready` → `no response` | 터널 창이 닫혔다 |
| 연결은 되는데 테이블이 없다 | 15432가 아니라 로컬 5432에 붙었다 |
| 엔드포인트가 503 | `.env`에 `REGION_PRICE_PROVIDER=database`가 빠졌다 |
