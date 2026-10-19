"""Application settings loaded from environment variables.

Secrets are never committed. Required values fail fast at startup.
"""

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTREE_", extra="ignore")

    environment: Environment = Environment.DEV
    # SecretStr keeps URLs (which contain passwords) out of reprs and logs.
    # The application URL must use the unprivileged `agentree_app` role.
    database_url: SecretStr = Field(
        description="App role URL, e.g. postgresql+asyncpg://agentree_app:pass@host:5432/db",
    )
    # Migrations run as `agentree_migrator`, the owner of all tables. Never used by the app.
    migration_database_url: SecretStr | None = None
    db_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
