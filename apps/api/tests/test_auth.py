"""Authentication flows against the real app and database."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agentree.core.tokens import hash_token
from tests.conftest import WEB_ORIGIN, AppHarness
from tests.helpers import PASSWORD, signup, unique_email

COOKIE = "__Host-agentree_session"


# --- registration & verification ---------------------------------------------------------


async def test_register_verify_login_me_logout(harness: AppHarness) -> None:
    acc = await signup(harness)
    me = await acc.client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == acc.email and me.json()["email_verified"] is True

    r = await acc.client.post("/api/auth/logout")
    assert r.status_code == 200
    assert (await acc.client.get("/api/auth/me")).status_code == 401


async def test_password_is_stored_as_argon2id(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    acc = await signup(harness)
    async with migrator_engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT password_hash FROM users WHERE email_normalized = :e"),
                {"e": acc.email},
            )
        ).scalar_one()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


async def test_session_cookie_flags(harness: AppHarness) -> None:
    email = unique_email()
    acc = await signup(harness, email, login=False)
    r = await acc.client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert "domain=" not in cookie.lower()


async def test_session_token_is_stored_hashed(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    acc = await signup(harness)
    raw = acc.client.cookies[COOKIE]
    async with migrator_engine.connect() as conn:
        hashes = (await conn.execute(text("SELECT token_hash FROM user_sessions"))).scalars().all()
    assert hash_token(raw) in hashes
    assert raw not in hashes


async def test_register_does_not_reveal_existing_accounts(harness: AppHarness) -> None:
    acc = await signup(harness)
    c = harness.new_client()
    r = await c.post("/api/auth/register", json={"email": acc.email, "password": PASSWORD + "x"})
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}
    assert "sign-up attempt" in harness.mailer.last_to(acc.email).subject
    # The original password still works; no second account was created.
    r = await c.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    assert r.status_code == 200


@pytest.mark.parametrize("password", ["short", "x" * 257])
async def test_weak_passwords_rejected(client: AsyncClient, password: str) -> None:
    r = await client.post(
        "/api/auth/register", json={"email": unique_email(), "password": password}
    )
    assert r.status_code == 422


async def test_password_equal_to_email_rejected(client: AsyncClient) -> None:
    email = unique_email()
    r = await client.post("/api/auth/register", json={"email": email, "password": email})
    assert r.status_code == 422


async def test_unverified_user_cannot_log_in(harness: AppHarness) -> None:
    acc = await signup(harness, verify=False, login=False)
    r = await acc.client.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["detail"] == "email_not_verified"


async def test_verification_token_is_single_use(harness: AppHarness) -> None:
    acc = await signup(harness, verify=False, login=False)
    token = harness.mailer.token_for(acc.email)
    assert (
        await acc.client.post("/api/auth/verify-email", json={"token": token})
    ).status_code == 200
    assert (
        await acc.client.post("/api/auth/verify-email", json={"token": token})
    ).status_code == 400


async def test_expired_verification_token_rejected(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    acc = await signup(harness, verify=False, login=False)
    token = harness.mailer.token_for(acc.email)
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE auth_tokens SET expires_at = now() - interval '1 second' WHERE token_hash = :h"
            ),
            {"h": hash_token(token)},
        )
    assert (
        await acc.client.post("/api/auth/verify-email", json={"token": token})
    ).status_code == 400


async def test_resend_verification_invalidates_previous_token(harness: AppHarness) -> None:
    acc = await signup(harness, verify=False, login=False)
    old = harness.mailer.token_for(acc.email)
    r = await acc.client.post("/api/auth/resend-verification", json={"email": acc.email})
    assert r.status_code == 202
    new = harness.mailer.token_for(acc.email)
    assert new != old
    assert (await acc.client.post("/api/auth/verify-email", json={"token": old})).status_code == 400
    assert (await acc.client.post("/api/auth/verify-email", json={"token": new})).status_code == 200


# --- login & sessions ----------------------------------------------------------------------


async def test_login_errors_are_generic(harness: AppHarness) -> None:
    acc = await signup(harness)
    c = harness.new_client()
    wrong_pw = await c.post(
        "/api/auth/login", json={"email": acc.email, "password": "wrong password!"}
    )
    no_user = await c.post("/api/auth/login", json={"email": unique_email(), "password": PASSWORD})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json() == {"detail": "invalid_credentials"}


async def test_each_login_issues_a_new_session_token(harness: AppHarness) -> None:
    acc = await signup(harness)
    first = acc.client.cookies[COOKIE]
    r = await acc.client.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    assert r.status_code == 200
    assert acc.client.cookies[COOKIE] != first


async def test_forged_or_missing_cookie_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/auth/me")).status_code == 401
    client.cookies.set(COOKIE, "forged-token-value-that-is-long-enough")
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("expires_at", "now() - interval '1 second'"),
        ("last_seen_at", "now() - interval '13 hours'"),
    ],
)
async def test_expired_sessions_are_rejected(
    harness: AppHarness, migrator_engine: AsyncEngine, column: str, value: str
) -> None:
    acc = await signup(harness)
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE user_sessions SET {column} = {value} WHERE token_hash = :h"),
            {"h": hash_token(acc.client.cookies[COOKIE])},
        )
    assert (await acc.client.get("/api/auth/me")).status_code == 401


async def test_logout_all_revokes_every_session(harness: AppHarness) -> None:
    acc = await signup(harness)
    other = harness.new_client()
    await other.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    assert (await other.get("/api/auth/me")).status_code == 200
    assert (await acc.client.post("/api/auth/logout-all")).status_code == 200
    assert (await other.get("/api/auth/me")).status_code == 401
    assert (await acc.client.get("/api/auth/me")).status_code == 401


async def test_revoked_cookie_cannot_be_replayed(harness: AppHarness) -> None:
    acc = await signup(harness)
    raw = acc.client.cookies[COOKIE]
    await acc.client.post("/api/auth/logout")
    replay = harness.new_client()
    replay.cookies.set(COOKIE, raw)
    assert (await replay.get("/api/auth/me")).status_code == 401


# --- password reset & change ---------------------------------------------------------------


async def test_password_reset_flow_revokes_sessions(harness: AppHarness) -> None:
    acc = await signup(harness)
    c = harness.new_client()
    r = await c.post("/api/auth/password-reset/request", json={"email": acc.email})
    assert r.status_code == 202
    token = harness.mailer.token_for(acc.email)
    new_pw = "a brand new long passphrase"
    r = await c.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": new_pw}
    )
    assert r.status_code == 200
    assert (await acc.client.get("/api/auth/me")).status_code == 401  # old session revoked
    assert (
        await c.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    ).status_code == 401
    assert (
        await c.post("/api/auth/login", json={"email": acc.email, "password": new_pw})
    ).status_code == 200
    # single use
    r = await c.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": new_pw + "!"}
    )
    assert r.status_code == 400


async def test_password_reset_request_for_unknown_email_looks_identical(
    harness: AppHarness,
) -> None:
    c = harness.new_client()
    before = len(harness.mailer.sent)
    r = await c.post("/api/auth/password-reset/request", json={"email": unique_email()})
    assert r.status_code == 202 and r.json() == {"status": "accepted"}
    assert len(harness.mailer.sent) == before


async def test_weak_reset_password_does_not_consume_token(harness: AppHarness) -> None:
    acc = await signup(harness)
    await acc.client.post("/api/auth/password-reset/request", json={"email": acc.email})
    token = harness.mailer.token_for(acc.email)
    r = await acc.client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": "short"}
    )
    assert r.status_code == 422
    r = await acc.client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "long enough passphrase"},
    )
    assert r.status_code == 200


async def test_change_password_keeps_current_session_and_revokes_others(
    harness: AppHarness,
) -> None:
    acc = await signup(harness)
    other = harness.new_client()
    await other.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    r = await acc.client.post(
        "/api/auth/password/change",
        json={"current_password": PASSWORD, "new_password": "another long passphrase"},
    )
    assert r.status_code == 200
    assert (await acc.client.get("/api/auth/me")).status_code == 200
    assert (await other.get("/api/auth/me")).status_code == 401


async def test_change_password_requires_current_password(harness: AppHarness) -> None:
    acc = await signup(harness)
    r = await acc.client.post(
        "/api/auth/password/change",
        json={"current_password": "not my password", "new_password": "another long passphrase"},
    )
    assert r.status_code == 400


# --- CSRF & rate limiting ------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://evil.example"}, {"Origin": "null"}])
async def test_state_changing_requests_require_allowed_origin(
    harness: AppHarness, headers: dict[str, str]
) -> None:
    acc = await signup(harness)
    c = harness.new_client()
    c.headers.pop("Origin")
    c.cookies.set(COOKIE, acc.client.cookies[COOKIE])
    r = await c.post("/api/auth/logout-all", headers=headers)
    assert r.status_code == 403
    assert r.json() == {"detail": "origin_not_allowed"}
    assert (await acc.client.get("/api/auth/me")).status_code == 200  # nothing was revoked


async def test_referer_from_allowed_origin_is_accepted(harness: AppHarness) -> None:
    acc = await signup(harness)
    acc.client.headers.pop("Origin")
    r = await acc.client.post("/api/auth/logout", headers={"Referer": f"{WEB_ORIGIN}/settings"})
    assert r.status_code == 200


async def test_login_is_rate_limited_per_email(harness: AppHarness) -> None:
    acc = await signup(harness)
    c = harness.new_client()
    codes = [
        (
            await c.post(
                "/api/auth/login", json={"email": acc.email, "password": "wrong password!"}
            )
        ).status_code
        for _ in range(11)
    ]
    # signup() already logged in once for this email: 9 more failures reach the limit of 10.
    assert codes[:9] == [401] * 9
    assert codes[9:] == [429, 429]
    # Even the right password is refused while limited.
    r = await c.post("/api/auth/login", json={"email": acc.email, "password": PASSWORD})
    assert r.status_code == 429


async def test_password_reset_request_is_rate_limited(harness: AppHarness) -> None:
    email = unique_email()
    c = harness.new_client()
    codes = [
        (await c.post("/api/auth/password-reset/request", json={"email": email})).status_code
        for _ in range(6)
    ]
    assert codes == [202] * 5 + [429]


def test_session_cookie_name_without_secure_flag() -> None:
    from agentree.core.config import Settings

    s = Settings(database_url="postgresql+asyncpg://x:y@h/d", session_cookie_secure=False)
    assert s.session_cookie_name == "agentree_session"
