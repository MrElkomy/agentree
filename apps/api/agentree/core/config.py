"""Application settings loaded from environment variables.

Secrets are never committed. Required values fail fast at startup.
"""

from enum import StrEnum
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentree.core.vault import parse_master_key


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

    # Dev/E2E only: replace every AI provider with a canned demo reply (no network calls).
    llm_demo_mode: bool = False

    # BYOK vault master key: base64 of 32 random bytes. Required to store/read provider keys.
    master_key: SecretStr | None = None
    master_key_id: str = "k1"
    # Retired keys still needed to decrypt older secrets: JSON {"k0": "<base64>"}.
    previous_master_keys: dict[str, SecretStr] = {}

    @model_validator(mode="after")
    def _deployed_environments_must_be_secure(self) -> "Settings":
        """Fail closed at startup on insecure cookie, origin or email settings."""
        if self.environment not in (Environment.STAGING, Environment.PRODUCTION):
            return self
        problems: list[str] = []
        if not self.session_cookie_secure:
            problems.append("session_cookie_secure must be true")
        if not self.allowed_origins:
            problems.append("allowed_origins must not be empty")
        for origin in [*self.allowed_origins, self.public_base_url]:
            parts = urlsplit(origin)
            if parts.scheme != "https" or not parts.hostname or _is_local(parts.hostname):
                problems.append(f"{origin!r} must be an https URL on a public host")
        if _is_local(self.smtp_host):
            problems.append("smtp_host must not be a local/development mail server")
        if not self.smtp_starttls:
            problems.append("smtp_starttls must be true")
        if not (self.smtp_username and self.smtp_password):
            problems.append("smtp_username and smtp_password are required")
        if "localhost" in self.mail_from:
            problems.append("mail_from must use a real sending domain")
        if self.master_key is None:
            problems.append("master_key is required")
        if self.llm_demo_mode:
            problems.append("llm_demo_mode must be false")
        if problems:
            raise ValueError(f"insecure {self.environment} configuration: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _master_keys_are_valid(self) -> "Settings":
        for value in [self.master_key, *self.previous_master_keys.values()]:
            if value is not None:
                parse_master_key(value.get_secret_value())
        if self.master_key_id in self.previous_master_keys:
            raise ValueError("master_key_id must differ from previous key ids")
        return self

    @property
    def session_cookie_name(self) -> str:
        # __Host- prefix pins the cookie to this exact host, path=/ and Secure.
        return "__Host-agentree_session" if self.session_cookie_secure else "agentree_session"


def _is_local(host: str) -> bool:
    host = host.lower()
    return (
        host in {"localhost", "mailpit", "0.0.0.0", "::1"}  # noqa: S104 (comparison only)
        or host.startswith("127.")
        or host.endswith((".local", ".localhost", ".test", ".internal"))
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
