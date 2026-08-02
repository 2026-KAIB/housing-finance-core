from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    app_name: str = "Housing Finance Core"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    database_url: str | None = None
    database_host: str = "localhost"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "housing"
    database_user: str = "housing"
    database_password: SecretStr | None = None
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    loan_product_provider: Literal["json", "database"] = "json"
    # 예·적금은 아직 JSON 스냅샷을 뜬 적이 없어 갈래가 하나다. "none"이 기본인
    # 이유는 DB가 없는 환경에서 예·적금 구간이 조용히 빈 목록으로 도는 것보다
    # "공급원이 없다"고 막히는 편이 맞기 때문이다.
    savings_product_provider: Literal["none", "database"] = "none"
    # 시세 통계에는 JSON 폴백을 두지 않는다 — 가짜 시세를 보여주면 안 되는
    # 데이터이므로, 공급자가 없으면 해당 엔드포인트만 503을 낸다. 기본값이
    # disabled인 덕분에 DB 터널을 열지 않은 로컬에서도 앱 전체는 뜬다.
    region_price_provider: Literal["disabled", "database"] = "disabled"
    property_listing_json_path: Path = Path(
        "sample_data/property_listings/property_listings.v1.json"
    )
    loan_product_base_json_path: Path = Path(
        "sample_data/loan_products/loan_base_rows_2026-07-31.json"
    )
    loan_product_option_json_path: Path = Path(
        "sample_data/loan_products/loan_option_rows_2026-07-31.json"
    )
    cors_origins: str = "http://localhost:3000"

    # 보고서 설명 생성용. 키는 환경변수(`GEMINI_API_KEY`) 또는 `.env`에서만 읽고
    # 코드·테스트·픽스처에 값을 넣지 않는다. 없으면 AI 설명을 생략하고 고정
    # 템플릿 보고서만 제공한다(reports/README의 "AI 호출 실패 시에도" 규약).
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 30.0
    # 무료 등급은 제출한 프롬프트를 검토·학습에 사용할 수 있다고 Google이 약관에
    # 명시한다. 그래서 전송 전 개인정보 게이트를 기본 활성으로 두고, 끄려면
    # 명시적으로 꺼야 한다(`reports/ai_explanation/egress.py`).
    report_ai_egress_guard: bool = True

    # 보고서 PDF 보관. 기본이 "none"인 이유는 보관이 **되돌리기 어려운 부수효과**
    # 이기 때문이다 — 켜는 순간 계산 요청마다 디스크에 파일이 쌓이고 개인 재무
    # 정보가 담긴 문서가 영구 저장된다. 그건 명시적으로 켜야 하는 결정이다.
    # ``filesystem``은 이름 그대로 파일시스템만으로 완결된다 — 본문과 기록이 모두
    # 보관 루트 아래 놓이므로 DB 없이도 보고서를 만들고 다시 꺼낼 수 있다. DB가
    # 설정돼 있으면 색인 행을 하나 더 남기지만, 그건 부차적이라 실패해도 보관을
    # 무르지 않는다(`services/report_archive.py`).
    report_archive_provider: Literal["none", "filesystem"] = "none"
    # 보관 루트. 파일명은 서버가 만든 UUID로만 구성되며 사용자 입력이 경로에
    # 섞이지 않는다(`reports/storage.py`).
    report_storage_root: Path = Path("var/reports")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
