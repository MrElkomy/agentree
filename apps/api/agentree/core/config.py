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

    # Web origins allowed to make state-changing requests (CSRF Origin check).
    allowed_origins: list[str] = ["http://localhost:3000"]
    # Base URL of the web app, used in email links.
    public_base_url: str = "http://localhost:3000"

    # Sessions
    session_cookie_secure: bool = True
    session_idle_timeout_minutes: int = Field(default=12 * 60, gt=0)
    session_absolute_timeout_hours: int = Field(default=14 * 24, gt=0)

    # One-time token lifetimes
    email_verification_ttl_hours: int = Field(default=24, gt=0)
    password_reset_ttl_minutes: int = Field(default=60, gt=0)
    invitation_ttl_days: int = Field(default=7, gt=0)

    # Outbound email (Mailpit in dev: host=localhost/mailpit, port=1025, no TLS)
    mail_from: str = "Agentree <no-reply@localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False

    @property
    def session_cookie_name(self) -> str:
        # __Host- prefix pins the cookie to this exact host, path=/ and Secure.
        return "__Host-agentree_session" if self.session_cookie_secure else "agentree_session"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
