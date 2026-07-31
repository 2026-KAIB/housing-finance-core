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

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
