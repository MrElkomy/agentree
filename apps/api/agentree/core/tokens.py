"""Opaque random tokens. Only the SHA-256 hash is ever stored."""

import hashlib
import secrets


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token() -> tuple[str, str]:
    """Return (raw token for the client, hash for storage). 256 bits of entropy."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)
