"""보관된 보고서의 **메타데이터** 테이블.

파일 본문은 여기 넣지 않는다:
    PDF는 사용자·매물마다 하나씩 쌓이고 한 건이 수백 KB다. 행에 BLOB으로 넣으면
    백업·복제·조회가 전부 그 무게를 같이 진다. 본문은 저장소(``reports/storage``)에
    두고 이 표는 **어디에 무엇이 있는지**와 그 문서를 신뢰할 수 있는지만 기록한다.

왜 as_of와 policy_sources를 행에 박는가:
    PDF는 만든 순간의 스냅샷이다. 예금자보호 한도(5천만 → 1억)처럼 시행일이 있는
    상수가 바뀌면 **과거 문서는 과거 기준이 맞다.** 나중에 "이 문서는 언제 기준이냐"에
    답하지 못하면 보관 자체가 위험해진다. 파일 안에도 찍히지만, 파일을 열지 않고
    질의할 수 있어야 하므로 행에도 남긴다.

왜 채택 내역을 남기는가:
    두 에이전트를 통과하지 못한 절은 **수치만** 실린다. 그 사실을 잃은 채 PDF만
    남기면 부분 검증된 문서와 완전 검증된 문서가 구별되지 않는다.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
)

# 상품 테이블은 이 저장소 밖에서 만들어졌다. 같은 MetaData에 섞으면 자동 생성·
# 자동 비교가 남의 표까지 건드리므로 보고서 전용 MetaData를 따로 둔다.
report_metadata = MetaData()

REPORT_KINDS = ("simulation", "property")

reports_table = Table(
    "generated_reports",
    report_metadata,
    Column("id", Uuid, primary_key=True),
    # 어떤 종류의 보고서인가. 종류마다 막아야 하는 오류가 달라 서술 규칙도 다르다.
    Column("kind", String(32), nullable=False),
    # 이 문서를 낳은 계산의 식별자(simulation_id 또는 search_snapshot_id).
    Column("source_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # 계산 기준일. 규제 상수의 시점을 되짚는 축이다.
    Column("as_of", Date, nullable=False),
    Column("media_type", String(64), nullable=False),
    Column("byte_size", Integer, nullable=False),
    # 저장소가 바뀌어도 같은 파일인지 확인할 수 있게 내용 해시를 남긴다.
    Column("content_sha256", String(64), nullable=False),
    # 저장소 루트 기준 **상대** 경로. 절대 경로를 넣으면 배포 위치가 바뀔 때
    # 행 전체가 못 쓰게 된다.
    Column("storage_path", String(512), nullable=False),
    Column("fully_verified", Boolean, nullable=False),
    Column("adopted_sections", JSON, nullable=False),
    Column("figures_only_sections", JSON, nullable=False),
    Column("policy_sources", JSON, nullable=False),
    Column("notes", JSON, nullable=False),
)


__all__ = ["REPORT_KINDS", "report_metadata", "reports_table"]
