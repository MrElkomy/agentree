"""Shared helpers for API tests."""

import uuid
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient

from tests.conftest import AppHarness

PASSWORD = "correct horse battery staple"  # noqa: S105


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def unique_slug(prefix: str = "biz") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class Account:
    client: AsyncClient
    email: str
    id: uuid.UUID


async def signup(h: AppHarness, email: str | None = None, *, verify: bool = True,
                 login: bool = True) -> Account:  # fmt: skip
    email = email or unique_email()
    c = h.new_client()
    r = await c.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 202, r.text
    if verify:
        token = h.mailer.token_for(email)
        r = await c.post("/api/auth/verify-email", json={"token": token})
        assert r.status_code == 200, r.text
    user_id = uuid.UUID(int=0)
    if login and verify:
        r = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        user_id = uuid.UUID(r.json()["id"])
    return Account(c, email, user_id)


async def create_business(acc: Account, name: str = "Acme") -> dict[str, Any]:
    r = await acc.client.post("/api/businesses", json={"name": name, "slug": unique_slug()})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


async def invite_and_join(h: AppHarness, owner: Account, business_id: str, role: str) -> Account:
    invitee = await signup(h)
    r = await owner.client.post(
        f"/api/businesses/{business_id}/invitations", json={"email": invitee.email, "role": role}
    )
    assert r.status_code == 201, r.text
    token = h.mailer.token_for(invitee.email)
    r = await invitee.client.post("/api/invitations/accept", json={"token": token})
    assert r.status_code == 200, r.text
    return invitee
