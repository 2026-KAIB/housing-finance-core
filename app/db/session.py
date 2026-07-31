"""SQLAlchemy engine lifecycle and safe database URL construction."""

from functools import lru_cache

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine, make_url

from app.core.config import Settings, get_settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when the database provider is enabled without usable credentials."""


def build_database_url(config: Settings) -> URL:
    """Build a SQLAlchemy URL without concatenating or logging the password."""

    if config.database_url:
        return make_url(config.database_url)
    if config.database_password is None:
        raise DatabaseConfigurationError(
            "DATABASE_PASSWORD or DATABASE_URL is required for the database provider"
        )
    return URL.create(
        drivername="postgresql+psycopg",
        username=config.database_user,
        password=config.database_password.get_secret_value(),
        host=config.database_host,
        port=config.database_port,
        database=config.database_name,
    )


@lru_cache
def get_database_engine() -> Engine:
    """Return the process-wide, bounded PostgreSQL connection pool."""

    config = get_settings()
    return create_engine(
        build_database_url(config),
        pool_pre_ping=True,
        pool_size=config.database_pool_size,
        max_overflow=config.database_max_overflow,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": config.database_connect_timeout_seconds,
            "application_name": "housing-finance-core",
        },
    )


__all__ = [
    "DatabaseConfigurationError",
    "build_database_url",
    "get_database_engine",
]
