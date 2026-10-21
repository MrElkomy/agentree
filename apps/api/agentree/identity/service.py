"""Identity service: accounts, sessions, email verification and password reset.

Public interface of the identity module. Never returns password hashes or raw stored
token hashes to callers.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.core.config import Settings
from agentree.core.email import EmailSender, OutgoingEmail, send_safely
from agentree.core.ids import uuid7
from agentree.core.tokens import hash_token, new_token
from agentree.identity.models import AuthToken, User, UserSession
from agentree.identity.passwords import (
    hash_password,
    needs_rehash,
    validate_new_password,
    verify_password,
)

Factory = async_sessionmaker[AsyncSession]


class TokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"  # noqa: S105 (token purpose label, not a secret)


class EmailNotVerifiedError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str
    email_verified: bool
    session_id: UUID


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _now() -> datetime:
    return datetime.now(UTC)


async def _issue_token(
    session: AsyncSession, user_id: UUID, purpose: TokenPurpose, ttl: timedelta
) -> str:
    # A new token invalidates any earlier unused token of the same purpose.
    await session.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user_id, AuthToken.purpose == purpose,
               AuthToken.used_at.is_(None))
        .values(used_at=_now())
    )  # fmt: skip
    raw, digest = new_token()
    session.add(
        AuthToken(
            id=uuid7(), user_id=user_id, purpose=purpose, token_hash=digest,
            expires_at=_now() + ttl,
        )
    )  # fmt: skip
    return raw


async def _consume_token(session: AsyncSession, raw: str, purpose: TokenPurpose) -> UUID | None:
    """Atomically mark a valid token used and return its user id."""
    return (
        await session.execute(
            update(AuthToken)
            .where(
                AuthToken.token_hash == hash_token(raw),
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
                AuthToken.expires_at > _now(),
            )
            .values(used_at=_now())
            .returning(AuthToken.user_id)
        )
    ).scalar_one_or_none()


# --- registration and verification ------------------------------------------------------


async def register(
    factory: Factory, settings: Settings, mailer: EmailSender, *, email: str, password: str
) -> None:
    """Create an unverified account and email a verification link.

    Behaves identically whether or not the email is already registered (no enumeration);
    an existing account owner gets a notice instead of a second account.
    """
    normalized = normalize_email(email)
    validate_new_password(password, normalized)
    # Hash before branching so both paths cost the same (no timing-based enumeration).
    password_hash = hash_password(password)
    async with factory() as session, session.begin():
        existing = (
            await session.execute(select(User.id).where(User.email_normalized == normalized))
        ).scalar_one_or_none()
        if existing is None:
            user = User(
                id=uuid7(), email=email.strip(), email_normalized=normalized,
                password_hash=password_hash,
            )  # fmt: skip
            session.add(user)
            await session.flush()
            raw = await _issue_token(
                session, user.id, TokenPurpose.VERIFY_EMAIL,
                timedelta(hours=settings.email_verification_ttl_hours),
            )  # fmt: skip
            message = OutgoingEmail(
                to=normalized,
                subject="Verify your Agentree email",
                body=f"Confirm your email: {settings.public_base_url}/verify-email?token={raw}",
            )
        else:
            message = OutgoingEmail(
                to=normalized,
                subject="Agentree sign-up attempt",
                body="Someone tried to create an Agentree account with this email. "
                f"If it was you, sign in or reset your password: {settings.public_base_url}/login",
            )
    await send_safely(mailer, message, kind="registration")


async def resend_verification(
    factory: Factory, settings: Settings, mailer: EmailSender, *, email: str
) -> None:
    normalized = normalize_email(email)
    async with factory() as session, session.begin():
        user = (
            await session.execute(select(User).where(User.email_normalized == normalized))
        ).scalar_one_or_none()
        if user is None or user.email_verified_at is not None:
            return
        raw = await _issue_token(
            session, user.id, TokenPurpose.VERIFY_EMAIL,
            timedelta(hours=settings.email_verification_ttl_hours),
        )  # fmt: skip
    await send_safely(
        mailer,
        OutgoingEmail(
            to=normalized,
            subject="Verify your Agentree email",
            body=f"Confirm your email: {settings.public_base_url}/verify-email?token={raw}",
        ),
        kind="verification",
    )


async def verify_email(factory: Factory, raw_token: str) -> bool:
    async with factory() as session, session.begin():
        user_id = await _consume_token(session, raw_token, TokenPurpose.VERIFY_EMAIL)
        if user_id is None:
            return False
        await session.execute(
            update(User)
            .where(User.id == user_id, User.email_verified_at.is_(None))
            .values(email_verified_at=_now())
        )
    return True


# --- login and sessions -----------------------------------------------------------------


async def authenticate(factory: Factory, *, email: str, password: str) -> UUID | None:
    """Return the user id for valid credentials. Raises EmailNotVerifiedError if unverified."""
    async with factory() as session, session.begin():
        user = (
            await session.execute(
                select(User).where(User.email_normalized == normalize_email(email))
            )
        ).scalar_one_or_none()
        if not verify_password(user.password_hash if user else None, password) or user is None:
            return None
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        if user.email_verified_at is None:
            raise EmailNotVerifiedError
        return user.id


async def create_session(factory: Factory, settings: Settings, user_id: UUID) -> str:
    """Start a new session (fresh token on every login: no fixation). Returns the raw token."""
    raw, digest = new_token()
    async with factory() as session, session.begin():
        session.add(
            UserSession(
                id=uuid7(), user_id=user_id, token_hash=digest,
                expires_at=_now() + timedelta(hours=settings.session_absolute_timeout_hours),
            )
        )  # fmt: skip
    return raw


async def resolve_session(
    factory: Factory, settings: Settings, raw_token: str
) -> AuthenticatedUser | None:
    now = _now()
    idle_cutoff = now - timedelta(minutes=settings.session_idle_timeout_minutes)
    async with factory() as session, session.begin():
        row = (
            await session.execute(
                select(UserSession, User)
                .join(User, User.id == UserSession.user_id)
                .where(
                    UserSession.token_hash == hash_token(raw_token),
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                    UserSession.last_seen_at > idle_cutoff,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        user_session, user = row
        # Throttle writes: refresh idle timer at most once a minute.
        if user_session.last_seen_at < now - timedelta(minutes=1):
            user_session.last_seen_at = now
        return AuthenticatedUser(
            id=user.id, email=user.email_normalized,
            email_verified=user.email_verified_at is not None, session_id=user_session.id,
        )  # fmt: skip


async def revoke_session(factory: Factory, session_id: UUID) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            update(UserSession)
            .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=_now())
        )


async def revoke_all_sessions(
    session: AsyncSession, user_id: UUID, *, except_session_id: UUID | None = None
) -> None:
    stmt = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    await session.execute(stmt.values(revoked_at=_now()))


async def logout_everywhere(factory: Factory, user_id: UUID) -> None:
    async with factory() as session, session.begin():
        await revoke_all_sessions(session, user_id)


# --- passwords --------------------------------------------------------------------------


async def request_password_reset(
    factory: Factory, settings: Settings, mailer: EmailSender, *, email: str
) -> None:
    """Email a reset link if the account exists. Same outcome either way for the caller."""
    normalized = normalize_email(email)
    async with factory() as session, session.begin():
        user_id = (
            await session.execute(select(User.id).where(User.email_normalized == normalized))
        ).scalar_one_or_none()
        if user_id is None:
            return
        raw = await _issue_token(
            session, user_id, TokenPurpose.RESET_PASSWORD,
            timedelta(minutes=settings.password_reset_ttl_minutes),
        )  # fmt: skip
    await send_safely(
        mailer,
        OutgoingEmail(
            to=normalized,
            subject="Reset your Agentree password",
            body=f"Reset your password: {settings.public_base_url}/reset-password?token={raw}\n"
            "If you did not ask for this, ignore this email.",
        ),
        kind="password_reset",
    )


async def confirm_password_reset(factory: Factory, *, raw_token: str, new_password: str) -> bool:
    async with factory() as session, session.begin():
        user_id = await _consume_token(session, raw_token, TokenPurpose.RESET_PASSWORD)
        if user_id is None:
            return False
        user = await session.get(User, user_id)
        if user is None:  # user deleted after token issue
            return False
        validate_new_password(new_password, user.email_normalized)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = _now()
        # Reset proves email control.
        user.email_verified_at = user.email_verified_at or _now()
        await revoke_all_sessions(session, user_id)
    return True


async def change_password(
    factory: Factory, current: AuthenticatedUser, *, current_password: str, new_password: str
) -> bool:
    async with factory() as session, session.begin():
        user = await session.get(User, current.id)
        if user is None or not verify_password(user.password_hash, current_password):
            return False
        validate_new_password(new_password, user.email_normalized)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = _now()
        await revoke_all_sessions(session, user.id, except_session_id=current.session_id)
    return True


async def emails_for(factory: Factory, user_ids: set[UUID]) -> dict[UUID, str]:
    """Display emails for user ids (e.g. audit trail actors). Unknown ids are left out."""
    if not user_ids:
        return {}
    async with factory() as session:
        rows = await session.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        return {uid: email for uid, email in rows.all()}
