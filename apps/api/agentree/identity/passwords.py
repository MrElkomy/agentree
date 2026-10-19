"""Password hashing with Argon2id (argon2-cffi defaults)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id, library-maintained parameters
# Used to keep login timing similar when the account does not exist.
_DUMMY_HASH = _hasher.hash("agentree-dummy-password-for-timing")

MIN_LENGTH = 12
MAX_LENGTH = 256  # bounds hashing cost per request


class WeakPasswordError(ValueError):
    pass


def validate_new_password(password: str, email: str) -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise WeakPasswordError(f"password must be {MIN_LENGTH}-{MAX_LENGTH} characters")
    if password.strip().lower() == email.strip().lower():
        raise WeakPasswordError("password must not equal the email address")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
