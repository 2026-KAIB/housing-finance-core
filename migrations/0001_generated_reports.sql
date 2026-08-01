-- 보관된 보고서의 메타데이터 표.
--
-- 왜 Alembic 자동 생성이 아니라 손으로 쓴 SQL인가:
--   이 데이터베이스의 상품 테이블(financial_products, savings_rate_options 등)은
--   이 저장소 밖에서 만들어졌고 Alembic이 관리한 적이 없다. 지금 `alembic init` 후
--   autogenerate를 돌리면 모델에 없는 그 표들을 **삭제 대상으로 잡는다.** 첫 표
--   하나 때문에 남의 데이터를 지울 위험을 만들 이유가 없다.
--
--   Alembic은 이 저장소가 스키마 전체를 소유하게 될 때 초기화한다(migrations/README).
--
-- 적용:
--   psql "$DATABASE_URL" -f migrations/0001_generated_reports.sql
--
-- 파일 본문(PDF)은 이 표에 넣지 않는다. 저장소 루트 기준 상대 경로만 둔다.

CREATE TABLE IF NOT EXISTS generated_reports (
    id                    uuid         PRIMARY KEY,
    -- 'simulation' | 'property'
    kind                  varchar(32)  NOT NULL,
    -- 이 문서를 낳은 계산의 식별자(simulation_id 또는 search_snapshot_id).
    source_id             uuid         NOT NULL,
    created_at            timestamptz  NOT NULL,
    -- 계산 기준일. 규제 상수의 시점을 되짚는 축이라 반드시 남긴다.
    as_of                 date         NOT NULL,
    media_type            varchar(64)  NOT NULL,
    byte_size             integer      NOT NULL,
    content_sha256        varchar(64)  NOT NULL,
    storage_path          varchar(512) NOT NULL,
    -- 두 에이전트를 모두 통과했는가. 부분 검증 문서와 구별되어야 한다.
    fully_verified        boolean      NOT NULL,
    adopted_sections      jsonb        NOT NULL DEFAULT '[]'::jsonb,
    figures_only_sections jsonb        NOT NULL DEFAULT '[]'::jsonb,
    policy_sources        jsonb        NOT NULL DEFAULT '[]'::jsonb,
    notes                 jsonb        NOT NULL DEFAULT '[]'::jsonb,

    CONSTRAINT generated_reports_kind_check
        CHECK (kind IN ('simulation', 'property')),
    CONSTRAINT generated_reports_byte_size_check
        CHECK (byte_size > 0)
);

-- 같은 계산에서 나온 문서들을 최신순으로 찾는 질의가 기본 조회다.
CREATE INDEX IF NOT EXISTS generated_reports_source_created_idx
    ON generated_reports (source_id, created_at DESC);
