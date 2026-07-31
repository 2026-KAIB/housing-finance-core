import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.db.session import build_database_url


def test_database_url_is_built_without_manual_password_encoding() -> None:
    config = Settings(_env_file=None).model_copy(
        update={
            "database_url": None,
            "database_host": "postgres",
            "database_port": 5432,
            "database_name": "mydb",
            "database_user": "housing_api",
            "database_password": SecretStr("colon:@/ password"),
        }
    )

    url = build_database_url(config)

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "postgres"
    assert url.database == "mydb"
    assert url.username == "housing_api"
    assert url.password == "colon:@/ password"
    assert "colon:@/ password" not in str(url)


def test_explicit_database_url_takes_precedence() -> None:
    config = Settings(_env_file=None).model_copy(
        update={
            "database_url": "postgresql+psycopg://preferred:secret@db:5432/preferred",
            "database_host": "ignored",
        }
    )

    url = build_database_url(config)

    assert url.host == "db"
    assert url.database == "preferred"


def test_region_price_provider_defaults_to_disabled() -> None:
    config = Settings(_env_file=None)

    assert config.region_price_provider == "disabled"


def test_region_price_provider_accepts_database() -> None:
    config = Settings(_env_file=None, region_price_provider="database")

    assert config.region_price_provider == "database"


def test_region_price_provider_rejects_unknown_value() -> None:
    # model_copy는 검증을 건너뛰므로, 오타가 조용히 통과하지 않는지는
    # 생성자로 확인해야 한다.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, region_price_provider="postgres")
