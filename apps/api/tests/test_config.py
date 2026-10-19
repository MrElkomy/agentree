import pytest
from pydantic import ValidationError

from agentree.core.config import Settings


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTREE_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_database_url_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTREE_DATABASE_URL", "postgresql+asyncpg://u:hunter2@db/x")
    settings = Settings()
    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.model_dump())
