# 홈서버 백엔드 배포 안내

이 구성은 FastAPI를 외부에 직접 공개하지 않고, 같은 Docker 네트워크의
Next.js 서버만 API에 접근하게 한다.

```text
인터넷 :18082
  -> housing-finance-web:3000
  -> /api 프록시
  -> housing-finance-api:8000
  -> postgres:5432 (friend_dev_container)
```

공유기에는 프론트용 `18082/TCP`만 포트포워딩한다. 백엔드 `8000`과
PostgreSQL `5432`는 포트포워딩하지 않는다.

## 1. 현재까지 완료한 서버 조건

- Docker를 `dove` 계정으로 실행할 수 있다.
- `housing-platform` 외부 네트워크가 있다.
- `friend_dev_container`가 이 네트워크에 `postgres` 별칭으로 연결됐다.
- PostgreSQL은 `housing_api` 계정의 `mydb` 읽기 접근을 허용한다.
- `housing-postgresql.service`가 PostgreSQL 클러스터를 자동 시작한다.

확인은 다음처럼 한다.

```bash
systemctl is-active housing-postgresql.service
docker network inspect housing-platform
docker exec friend_dev_container pg_isready -h 127.0.0.1 -p 5432
```

`housing-postgresql.service`는 `active`, PostgreSQL은
`accepting connections`여야 한다. 기존 `friend_dev_container`는 개발
워크스페이스 이미지이므로 삭제하거나 `--force-recreate`하지 않는다.

## 2. 홈서버 환경 파일

공용 배포 디렉터리를 만든다.

```bash
sudo install -d -o dove -g dove -m 750 /opt/housing-finance
nano /opt/housing-finance/.env
```

`/opt/housing-finance/.env`에는 비밀값이 아닌 Docker 배포 설정을 넣는다.
프론트와 백엔드가 같은 파일을 사용한다.

```dotenv
WEB_BIND_ADDRESS=0.0.0.0
WEB_HOST_PORT=18082
BACKEND_API_URL=http://housing-finance-api:8000
PLATFORM_NETWORK=housing-platform
BACKEND_ENV_FILE=/opt/housing-finance/backend.env
```

백엔드 비밀 설정 파일을 별도로 만든다.

```bash
nano /opt/housing-finance/backend.env
chmod 600 /opt/housing-finance/backend.env
```

내용은 다음과 같다. `DATABASE_PASSWORD`에는 앞서 만든 `housing_api`의
실제 비밀번호를 넣는다. 이 비밀번호는 채팅이나 Git에 올리지 않는다.

```dotenv
APP_ENV=production
LOAN_PRODUCT_PROVIDER=database
REGION_PRICE_PROVIDER=database
SAVINGS_PRODUCT_PROVIDER=database
DATABASE_HOST=postgres
DATABASE_PORT=5432
DATABASE_NAME=mydb
DATABASE_USER=housing_api
DATABASE_PASSWORD=실제_비밀번호
DATABASE_CONNECT_TIMEOUT_SECONDS=5
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=5
PROPERTY_LISTING_JSON_PATH=sample_data/property_listings/property_listings.v1.json
CORS_ORIGINS=http://localhost:3000
REPORT_AI_EGRESS_GUARD=true
```

**공급자 세 줄을 모두 넣는다.** 구간마다 공급자가 따로이고 셋 다 기본값이
"끔"이라, 한 줄이 빠지면 DB가 멀쩡해도 그 구간만 막힌다. `REGION_PRICE_PROVIDER`가
없으면 실거래 조회가 503을 내고 화면에는 "실거래를 불러오지 못했습니다"만 뜬다.
`SAVINGS_PRODUCT_PROVIDER`가 없으면 예·적금 포트폴리오가 `NOT_RUN`으로 남는다.
DB 사용자는 `sgg_codes`, `apt_trades`를 포함해 각 구간이 읽는 테이블에
`SELECT` 권한이 있어야 한다 — 접속만 되고 권한이 없으면 같은 503으로 보인다.

비밀번호에 `#`, `$`, 공백 같은 문자가 있으면 값을 작은따옴표로 감싼다.
별도 필드로 전달하므로 URL 인코딩은 필요 없다. AI 보고서를 호출하려면 같은
파일에 `GEMINI_API_KEY`를 추가하고, 아직 사용하지 않으면 생략한다.

## 3. 자동 배포

워크플로가 `main` 반영 시 다음 작업을 수행한다.

1. Ruff와 전체 pytest 실행
2. `linux/amd64`, `linux/arm64` 이미지 생성
3. GHCR에 커밋 SHA 태그와 `main` 태그 발행
4. 홈서버 self-hosted runner에서 새 이미지 pull
5. `housing-finance-api`만 교체
6. `/ready`가 실제 상품 공급자를 조회하는지 확인
7. 실패 시 직전 이미지로 복구

GitHub 저장소에서 Linux self-hosted runner를 설치하고
`housing-production` 라벨을 붙인다. runner 서비스 계정은 Docker 그룹에
속해야 한다.

모든 준비를 끝낸 뒤 저장소의 Actions 변수에 다음 값을 만든다.

```text
ENABLE_HOME_DEPLOY=true
```

그 전에는 코드와 이미지만 검증·발행되고 홈서버 배포는 실행되지 않는다.

## 4. 수동 상태 확인

배포 뒤 홈서버에서 확인한다.

```bash
docker ps --filter name=housing-finance-api
docker logs --tail 200 housing-finance-api
docker inspect housing-finance-api \
  --format '{{range .NetworkSettings.Networks}}{{.NetworkID}} {{.IPAddress}}{{end}}'
docker exec housing-finance-api \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready').read().decode())"
```

정상 예시는 다음과 같다.

```json
{
  "status": "ready",
  "service": "Housing Finance Core",
  "loan_product_provider": "database",
  "loan_product_count": 9,
  "providers": {
    "loan_product": { "provider": "database", "status": "ok", "count": 9 },
    "savings_product": { "provider": "database", "status": "ok", "count": 23 },
    "region_price": { "provider": "database", "status": "ok" }
  }
}
```

개수는 DB 기준일과 유효기간에 따라 달라질 수 있다. 중요한 기준은 HTTP 200,
`database` 공급자 표시, 그리고 쿼리가 오류 없이 끝나는 것이다. `disabled`는
설정에서 그 구간을 끈 상태이고, `error`는 켜 놓고 조회에 실패한 상태다 —
`error`가 하나라도 있으면 503과 함께 어느 구간인지 `detail`에 나온다.

프론트까지 올라온 뒤에는 홈서버에서 다음을 확인한다. 프록시는 `/api/...`만
백엔드로 넘기므로 준비 확인도 API 접두사 경로로 건다.

```bash
curl --fail http://127.0.0.1:18082/health
curl -i http://127.0.0.1:18082/api/v1/health
curl -i http://127.0.0.1:18082/api/v1/ready
curl -i "http://127.0.0.1:18082/api/v1/properties/trades?sgg_code=11680"
```

## 5. 실행과 중단

백엔드만 중단하거나 다시 시작할 때 사용한다.

```bash
docker stop housing-finance-api
docker start housing-finance-api
```

전체 서비스 상태는 다음으로 본다.

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Networks}}'
```

`housing-finance-api`와 DB에는 외부 공개 포트가 없어야 한다. 기존 DB
컨테이너의 과거 호스트 포트 매핑은 별도 정리 전까지 건드리지 않는다.
