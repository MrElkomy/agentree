import pytest
from pydantic import ValidationError

from agentree.core.config import Settings
from agentree.core.vault import generate_master_key


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTREE_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_database_url_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTREE_DATABASE_URL", "postgresql+asyncpg://u:hunter2@db/x")
    settings = Settings()
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.model_dump())


SECURE_PROD: dict[str, object] = {
    "environment": "production",
    "database_url": "postgresql+asyncpg://agentree_app:x@db.example.com/agentree",
    "allowed_origins": ["https://app.agentree.com"],
    "public_base_url": "https://app.agentree.com",
    "session_cookie_secure": True,
    "smtp_host": "smtp.mailprovider.com",
    "smtp_port": 587,
    "smtp_starttls": True,
    "smtp_username": "apikey",
    "smtp_password": "not-a-real-secret",
    "mail_from": "Agentree <no-reply@agentree.com>",
    "master_key": generate_master_key(),
}


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_secure_deployed_configuration_is_accepted(environment: str) -> None:
    Settings.model_validate(SECURE_PROD | {"environment": environment})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"session_cookie_secure": False}, "session_cookie_secure"),
        ({"allowed_origins": []}, "allowed_origins"),
        ({"allowed_origins": ["http://app.agentree.com"]}, "https URL"),
        ({"allowed_origins": ["https://localhost:3000"]}, "https URL"),
        ({"public_base_url": "http://localhost:3000"}, "https URL"),
        ({"smtp_host": "mailpit"}, "smtp_host"),
        ({"smtp_host": "127.0.0.1"}, "smtp_host"),
        ({"smtp_starttls": False}, "smtp_starttls"),
        ({"smtp_password": None}, "smtp_username and smtp_password"),
        ({"mail_from": "Agentree <no-reply@localhost>"}, "mail_from"),
        ({"master_key": None}, "master_key is required"),
        ({"llm_demo_mode": True}, "llm_demo_mode must be false"),
    ],
)
def test_insecure_production_configuration_fails_closed(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(SECURE_PROD | override)


def test_dev_defaults_are_allowed_outside_deployed_environments() -> None:
    Settings(database_url="postgresql+asyncpg://u:p@localhost/d", session_cookie_secure=False)


@pytest.mark.parametrize("value", ["not-base64!!", "c2hvcnQ="])
def test_malformed_master_key_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+asyncpg://u:p@h/d", master_key=value)
