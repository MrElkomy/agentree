"""Audit trail: recorded events, Owner/Admin-only reads, append-only storage, tenant isolation."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.audit import service as audit
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.db import tenant_session
from tests.conftest import AppHarness
from tests.helpers import Account, create_business, invite_and_join, signup

Factory = async_sessionmaker[AsyncSession]
# The last 4 characters (the key hint) are not hex, so they cannot occur by chance in the ids
# and timestamps of the response (a hex hint such as "3c4d" matched a random UUID ~1% of runs).
SECRET = "sk-live-AUDITSECRET-1a2bWxYz"  # noqa: S105  # gitleaks:allow (fake test key)


async def _events(acc: Account, business_id: str, **params: Any) -> list[dict[str, Any]]:
    r = await acc.client.get(f"/api/businesses/{business_id}/audit-events", params=params)
    assert r.status_code == 200, r.text
    return r.json()["events"]  # type: ignore[no-any-return]


async def test_membership_lifecycle_is_audited(harness: AppHarness) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    base = f"/api/businesses/{b['id']}"
    admin = await invite_and_join(harness, owner, b["id"], "admin")
    r = await owner.client.patch(f"{base}/members/{admin.id}", json={"role": "member"})
    assert r.status_code == 200, r.text
    assert (await owner.client.delete(f"{base}/members/{admin.id}")).status_code == 204
    pending = await owner.client.post(
        f"{base}/invitations", json={"email": "later@example.com", "role": "member"}
    )
    assert (
        await owner.client.delete(f"{base}/invitations/{pending.json()['id']}")
    ).status_code == 204

    events = await _events(owner, b["id"])
    actions = [e["action"] for e in reversed(events)]  # oldest first
    assert actions == [
        "business.created", "invitation.created", "member.joined", "member.role_changed",
        "member.removed", "invitation.created", "invitation.revoked",
    ]  # fmt: skip
    by_action = {e["action"]: e for e in events}
    changed = by_action["member.role_changed"]
    assert changed["actor"] == {"user_id": str(owner.id), "email": owner.email}
    assert changed["target_type"] == "user" and changed["target_id"] == str(admin.id)
    assert changed["target_email"] == admin.email
    assert changed["details"] == {"from_role": "admin", "to_role": "member"}
    joined = by_action["member.joined"]
    assert joined["actor"]["user_id"] == str(admin.id) and joined["details"] == {"role": "admin"}
    assert by_action["invitation.revoked"]["target_id"] == pending.json()["id"]
    assert by_action["member.removed"]["details"] == {"role": "member"}


async def test_leaving_is_recorded_as_left(harness: AppHarness) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    member = await invite_and_join(harness, owner, b["id"], "member")
    r = await member.client.delete(f"/api/businesses/{b['id']}/members/{member.id}")
    assert r.status_code == 204, r.text
    latest = (await _events(owner, b["id"]))[0]
    assert latest["action"] == "member.left" and latest["actor"]["user_id"] == str(member.id)


async def test_unchanged_role_writes_no_event(harness: AppHarness) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    member = await invite_and_join(harness, owner, b["id"], "member")
    before = len(await _events(owner, b["id"]))
    r = await owner.client.patch(
        f"/api/businesses/{b['id']}/members/{member.id}", json={"role": "member"}
    )
    assert r.status_code == 200
    assert len(await _events(owner, b["id"])) == before


async def test_provider_key_changes_are_audited_without_the_key(harness: AppHarness) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    base = f"/api/businesses/{b['id']}/ai-providers/primary"
    body = {"provider": "openai", "model": "gpt-4o-mini", "api_key": SECRET, "verify": False}
    assert (await owner.client.put(base, json=body)).status_code == 200
    assert (await owner.client.put(base, json=body | {"verify": True})).status_code == 200
    assert (await owner.client.delete(base)).status_code == 204

    r = await owner.client.get(f"/api/businesses/{b['id']}/audit-events")
    assert SECRET not in r.text and SECRET[-4:] not in r.text  # neither key nor hint
    removed, replaced, first = r.json()["events"][:3]
    assert first["action"] == replaced["action"] == "provider_key.saved"
    assert first["details"] == {
        "slot": "primary", "provider": "openai", "model": "gpt-4o-mini",
        "replaced": False, "verified": False,
    }  # fmt: skip
    assert replaced["details"]["replaced"] is True and replaced["details"]["verified"] is True
    assert removed["action"] == "provider_key.removed" and removed["details"] == {"slot": "primary"}


@pytest.mark.parametrize(("role", "status"), [("admin", 200), ("member", 403)])
async def test_only_owners_and_admins_read_the_trail(
    harness: AppHarness, role: str, status: int
) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    user = await invite_and_join(harness, owner, b["id"], role)
    r = await user.client.get(f"/api/businesses/{b['id']}/audit-events")
    assert r.status_code == status


async def test_non_member_gets_not_found(harness: AppHarness) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    stranger = await signup(harness)
    r = await stranger.client.get(f"/api/businesses/{b['id']}/audit-events")
    assert r.status_code == 404


async def test_pagination_walks_every_event_once(harness: AppHarness) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    for i in range(4):
        r = await owner.client.post(
            f"/api/businesses/{b['id']}/invitations",
            json={"email": f"p{i}@example.com", "role": "member"},
        )
        assert r.status_code == 201
    seen: list[str] = []
    before: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2} | ({"before": before} if before else {})
        r = await owner.client.get(f"/api/businesses/{b['id']}/audit-events", params=params)
        page = r.json()
        seen += [e["id"] for e in page["events"]]
        before = page["next_before"]
        if before is None:
            break
    assert len(seen) == len(set(seen)) == 5  # business.created + 4 invitations
    assert seen == sorted(seen, reverse=True)
    r = await owner.client.get(f"/api/businesses/{b['id']}/audit-events", params={"limit": 101})
    assert r.status_code == 422


def _ctx(business_id: str | uuid.UUID) -> TenantContext:
    return TenantContext(uuid.UUID(str(business_id)), TenantSource.MEMBERSHIP)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_events SET action = 'member.removed'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
async def test_app_role_cannot_rewrite_or_erase_the_trail(
    harness: AppHarness, app_factory: Factory, sql: str
) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(app_factory, _ctx(b["id"])) as session:
            await session.execute(text(sql))
    assert len(await _events(owner, b["id"])) == 1


async def test_rls_hides_and_blocks_other_tenants(
    harness: AppHarness, app_factory: Factory
) -> None:
    alice, bob = await signup(harness), await signup(harness)
    a, b = await create_business(alice), await create_business(bob)
    async with tenant_session(app_factory, _ctx(a["id"])) as session:
        rows = (await session.execute(text("SELECT business_id FROM audit_events"))).scalars().all()
    assert {str(r) for r in rows} == {a["id"]}
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(app_factory, _ctx(a["id"])) as session:
            await audit.record(
                session, _ctx(b["id"]), action=audit.AuditAction.MEMBER_JOINED,
                actor_user_id=alice.id, target_type="user", target_id=alice.id,
            )  # fmt: skip
    async with app_factory() as session:  # no tenant context: nothing visible
        count = (await session.execute(text("SELECT count(*) FROM audit_events"))).scalar()
    assert count == 0


async def test_details_keep_only_allowlisted_scalars(
    harness: AppHarness, app_factory: Factory
) -> None:
    owner = await signup(harness)
    b = await create_business(owner)
    async with tenant_session(app_factory, _ctx(b["id"])) as session:
        await audit.record(
            session, _ctx(b["id"]), action=audit.AuditAction.PROVIDER_KEY_SAVED,
            actor_user_id=owner.id, target_type="provider_key", target_id="primary",
            details={"slot": "primary", "api_key": SECRET, "token": "t", "password": "p",
                     "model": "x" * 500, "provider": None},
        )  # fmt: skip
    latest = (await _events(owner, b["id"]))[0]
    assert latest["details"] == {"slot": "primary", "model": "x" * audit.MAX_DETAIL_LEN}
