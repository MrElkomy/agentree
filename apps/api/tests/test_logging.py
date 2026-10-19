import json
import logging

import pytest

from agentree.core.logging import REDACTED, JsonFormatter, redact, redact_text

FAKE_KEY = "sk-test-0123456789abcdefFAKE"


def _format(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter().format(record))  # type: ignore[no-any-return]


def _record(msg: str, *args: object, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_log_redaction_masks_secrets() -> None:
    out = _format(_record("calling provider with api_key=%s", FAKE_KEY))
    assert FAKE_KEY not in json.dumps(out)
    assert out["msg"] == f"calling provider with api_key={REDACTED}"


def test_structured_extras_are_redacted_recursively() -> None:
    out = _format(
        _record(
            "provider call",
            provider="example",
            credentials={"api_key": FAKE_KEY, "nested": {"refresh_token": "abc"}},
            content="customer said something private",
        )
    )
    dumped = json.dumps(out)
    assert FAKE_KEY not in dumped
    assert "abc" not in dumped
    assert "something private" not in dumped
    assert out["extra"]["provider"] == "example"  # type: ignore[index]


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("Authorization: Bearer eyJhbGciOi.abc.def", "eyJhbGciOi.abc.def"),
        ("postgresql+asyncpg://user:hunter2@db:5432/app", "hunter2"),
        ('password="correct horse"', "correct horse"),
        ("token: abc123", "abc123"),
    ],
)
def test_redact_text_patterns(raw: str, secret: str) -> None:
    assert secret not in redact_text(raw)


def test_exception_text_is_redacted() -> None:
    try:
        raise RuntimeError(f"failed with api_key={FAKE_KEY}")
    except RuntimeError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", (), sys.exc_info())
    assert FAKE_KEY not in JsonFormatter().format(record)


def test_redact_leaves_harmless_values() -> None:
    assert redact({"count": 3, "items": ["a", "b"]}) == {"count": 3, "items": ["a", "b"]}
