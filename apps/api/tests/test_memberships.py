"""Businesses, memberships, roles and invitations through the HTTP API."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agentree.core.tokens import hash_token
from tests.conftest import AppHarness
from tests.helpers import create_business, invite_and_join, signup, unique_slug


async def test_create_business_makes_creator_owner(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner, "Alpha")
    assert biz["role"] == "owner"
    listed = (await owner.client.get("/api/businesses")).json()
    assert [b["id"] for b in listed] == [biz["id"]]
    members = (await owner.client.get(f"/api/businesses/{biz['id']}/members")).json()
    assert members == [{"user_id": str(owner.id), "email": owner.email, "role": "owner"}]


async def test_unverified_user_cannot_create_business(harness: AppHarness) -> None:
    # Verified-then-session is required; an anonymous client is rejected outright.
    c = harness.new_client()
    r = await c.post("/api/businesses", json={"name": "X", "slug": unique_slug()})
    assert r.status_code == 401


@pytest.mark.parametrize("slug", ["api", "Bad Slug", "a"])
async def test_invalid_slug_rejected(harness: AppHarness, slug: str) -> None:
    owner = await signup(harness)
    r = await owner.client.post("/api/businesses", json={"name": "X", "slug": slug})
    assert r.status_code == 422


async def test_duplicate_slug_conflicts(harness: AppHarness) -> None:
    owner = await signup(harness)
    slug = unique_slug()
    assert (
        await owner.client.post("/api/businesses", json={"name": "A", "slug": slug})
    ).status_code == 201
    other = await signup(harness)
    assert (
        await other.client.post("/api/businesses", json={"name": "B", "slug": slug})
    ).status_code == 409


async def test_user_in_multiple_businesses_has_independent_roles(harness: AppHarness) -> None:
    alice = await signup(harness)
    bob = await signup(harness)
    a = await create_business(alice, "Alice Co")
    b = await create_business(bob, "Bob Co")
    # Bob invites Alice as a member of Bob Co.
    r = await bob.client.post(
        f"/api/businesses/{b['id']}/invitations", json={"email": alice.email, "role": "member"}
    )
    assert r.status_code == 201
    token = harness.mailer.token_for(alice.email)
    assert (
        await alice.client.post("/api/invitations/accept", json={"token": token})
    ).status_code == 200

    roles = {x["id"]: x["role"] for x in (await alice.client.get("/api/businesses")).json()}
    assert roles == {a["id"]: "owner", b["id"]: "member"}
    # Owner in A, but only member in B: cannot invite in B.
    r = await alice.client.post(
        f"/api/businesses/{b['id']}/invitations", json={"email": "x@example.com"}
    )
    assert r.status_code == 403
    r = await alice.client.post(
        f"/api/businesses/{a['id']}/invitations", json={"email": "x@example.com"}
    )
    assert r.status_code == 201


async def test_invitation_must_match_verified_email(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    intended = await signup(harness)
    attacker = await signup(harness)
    await owner.client.post(
        f"/api/businesses/{biz['id']}/invitations", json={"email": intended.email}
    )
    token = harness.mailer.token_for(intended.email)
    r = await attacker.client.post("/api/invitations/accept", json={"token": token})
    assert r.status_code == 400
    assert (await attacker.client.get(f"/api/businesses/{biz['id']}")).status_code == 404
    # The intended user can still accept.
    assert (
        await intended.client.post("/api/invitations/accept", json={"token": token})
    ).status_code == 200


async def test_invitation_is_single_use_and_revocable(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    invitee = await invite_and_join(harness, owner, biz["id"], "member")
    token = harness.mailer.token_for(invitee.email)
    assert (
        await invitee.client.post("/api/invitations/accept", json={"token": token})
    ).status_code == 400

    other = await signup(harness)
    r = await owner.client.post(
        f"/api/businesses/{biz['id']}/invitations", json={"email": other.email}
    )
    inv_id = r.json()["id"]
    assert (
        await owner.client.delete(f"/api/businesses/{biz['id']}/invitations/{inv_id}")
    ).status_code == 204
    token = harness.mailer.token_for(other.email)
    assert (
        await other.client.post("/api/invitations/accept", json={"token": token})
    ).status_code == 400


async def test_expired_invitation_rejected(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    invitee = await signup(harness)
    await owner.client.post(
        f"/api/businesses/{biz['id']}/invitations", json={"email": invitee.email}
    )
    token = harness.mailer.token_for(invitee.email)
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE business_invitations SET expires_at = now() - interval '1 second' WHERE token_hash = :h"
            ),
            {"h": hash_token(token)},
        )
    assert (
        await invitee.client.post("/api/invitations/accept", json={"token": token})
    ).status_code == 400


async def test_admin_cannot_invite_owner_but_owner_can(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    admin = await invite_and_join(harness, owner, biz["id"], "admin")
    r = await admin.client.post(
        f"/api/businesses/{biz['id']}/invitations", json={"email": "o@example.com", "role": "owner"}
    )
    assert r.status_code == 403
    r = await admin.client.post(
        f"/api/businesses/{biz['id']}/invitations", json={"email": "a@example.com", "role": "admin"}
    )
    assert r.status_code == 201


async def test_member_cannot_manage_members_or_see_invitations(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    member = await invite_and_join(harness, owner, biz["id"], "member")
    base = f"/api/businesses/{biz['id']}"
    assert (await member.client.get(f"{base}/members")).status_code == 200
    assert (await member.client.get(f"{base}/invitations")).status_code == 403
    assert (
        await member.client.patch(f"{base}/members/{owner.id}", json={"role": "member"})
    ).status_code == 403
    assert (await member.client.delete(f"{base}/members/{owner.id}")).status_code == 403


async def test_admin_manages_members_but_not_admins_or_owners(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    base = f"/api/businesses/{biz['id']}"
    admin = await invite_and_join(harness, owner, biz["id"], "admin")
    admin2 = await invite_and_join(harness, owner, biz["id"], "admin")
    member = await invite_and_join(harness, owner, biz["id"], "member")

    assert (
        await admin.client.patch(f"{base}/members/{member.id}", json={"role": "admin"})
    ).status_code == 200
    assert (
        await admin.client.patch(f"{base}/members/{admin2.id}", json={"role": "member"})
    ).status_code == 403
    assert (
        await admin.client.patch(f"{base}/members/{owner.id}", json={"role": "member"})
    ).status_code == 403
    assert (await admin.client.delete(f"{base}/members/{owner.id}")).status_code == 403


async def test_last_owner_cannot_be_demoted_or_removed(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    base = f"/api/businesses/{biz['id']}"
    assert (
        await owner.client.patch(f"{base}/members/{owner.id}", json={"role": "admin"})
    ).status_code == 409
    assert (await owner.client.delete(f"{base}/members/{owner.id}")).status_code == 409

    co_owner = await invite_and_join(harness, owner, biz["id"], "owner")
    assert (
        await owner.client.patch(f"{base}/members/{owner.id}", json={"role": "admin"})
    ).status_code == 200
    # co_owner is now the only owner
    assert (await co_owner.client.delete(f"{base}/members/{co_owner.id}")).status_code == 409


async def test_member_can_leave_and_loses_access(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    member = await invite_and_join(harness, owner, biz["id"], "member")
    base = f"/api/businesses/{biz['id']}"
    assert (await member.client.delete(f"{base}/members/{member.id}")).status_code == 204
    assert (await member.client.get(base)).status_code == 404
    assert (await member.client.get("/api/businesses")).json() == []


async def test_removed_member_loses_access_immediately(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    member = await invite_and_join(harness, owner, biz["id"], "member")
    base = f"/api/businesses/{biz['id']}"
    assert (await member.client.get(base)).status_code == 200
    assert (await owner.client.delete(f"{base}/members/{member.id}")).status_code == 204
    assert (await member.client.get(base)).status_code == 404
