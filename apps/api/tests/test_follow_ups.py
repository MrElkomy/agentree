"""Follow-up tasks: the agent's first-contact task, member tasks, and due reminders."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agentree.core.config import Settings
from agentree.leads import follow_ups
from tests.conftest import AppHarness
from tests.helpers import Account, create_business, invite_and_join, signup

Factory = async_sessionmaker[AsyncSession]
KEY = "sk-follow-up-key-eeee5555"  # gitleaks:allow (fake test key)


class Biz:
    def __init__(self, owner: Account, business: dict[str, Any]) -> None:
        self.owner, self.id, self.slug = owner, business["id"], business["slug"]
        self.base = f"/api/businesses/{self.id}"
        self.pub = f"/api/public/{self.slug}"


async def _lead(h: AppHarness, name: str = "Sara") -> tuple[Biz, dict[str, Any], dict[str, Any]]:
    owner = await signup(h)
    biz = Biz(owner, await create_business(owner, "Maple Chairs"))
    await owner.client.put(f"{biz.base}/ai-providers/primary", json={
        "provider": "openai", "model": "gpt-4o-mini", "api_key": KEY, "verify": False})  # fmt: skip
    await owner.client.put(f"{biz.base}/public-profile", json={"enabled": True})
    c = h.new_client()
    auth = {"X-Agentree-Guest": (await c.post(f"{biz.pub}/sessions")).json()["token"]}
    convo = (await c.post(f"{biz.pub}/chat", json={"message": "hi"}, headers=auth)).json()
    body = {"conversation_id": convo["conversation_id"], "name": name, "email": "s@example.com",
            "consent": True, "idempotency_key": uuid.uuid4().hex}  # fmt: skip
    for _ in range(2):  # a retried submission
        assert (await c.post(f"{biz.pub}/leads", json=body, headers=auth)).status_code == 200
    lead = (await owner.client.get(f"{biz.base}/leads")).json()["leads"][0]
    return biz, lead, {"client": c, "auth": auth, "body": body}


async def _tasks(acc: Account, biz: Biz, lead_id: str) -> list[dict[str, Any]]:
    r = await acc.client.get(f"{biz.base}/leads/{lead_id}/follow-ups")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _in(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


async def test_new_lead_gets_one_first_contact_task_from_the_agent(harness: AppHarness) -> None:
    biz, lead, visitor = await _lead(harness)
    tasks = await _tasks(biz.owner, biz, lead["id"])
    assert len(tasks) == 1
    task = tasks[0]
    assert task["kind"] == "first_contact" and task["status"] == "open"
    assert task["title"] == "Contact Sara" and task["created_by_agent"] == "sales"
    due = datetime.fromisoformat(task["due_at"])
    assert timedelta(hours=23) < due - datetime.now(UTC) <= timedelta(hours=24)
    assert lead["next_follow_up_at"] == task["due_at"]

    # The visitor re-submits new details: still one task.
    c, auth, body = visitor["client"], visitor["auth"], visitor["body"]
    r = await c.post(f"{biz.pub}/leads", headers=auth,
                     json=body | {"need": "More", "idempotency_key": uuid.uuid4().hex})  # fmt: skip
    assert r.status_code == 200
    assert len(await _tasks(biz.owner, biz, lead["id"])) == 1
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    created = [e for e in events if e["action"] == "follow_up.created"]
    assert len(created) == 1 and created[0]["details"] == {
        "kind": "first_contact",
        "agent": "sales",
    }


async def test_contacting_the_lead_closes_the_first_contact_task(harness: AppHarness) -> None:
    biz, lead, _ = await _lead(harness)
    r = await biz.owner.client.patch(f"{biz.base}/leads/{lead['id']}", json={"status": "contacted"})
    assert r.status_code == 200
    (task,) = await _tasks(biz.owner, biz, lead["id"])
    assert task["status"] == "done" and task["completed_at"] is not None
    listed = (await biz.owner.client.get(f"{biz.base}/leads")).json()["leads"][0]
    assert listed["next_follow_up_at"] is None


async def test_members_add_and_update_tasks(harness: AppHarness) -> None:
    biz, lead, _ = await _lead(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    url = f"{biz.base}/leads/{lead['id']}/follow-ups"
    r = await member.client.post(url, json={"title": "Send the catalog", "due_at": _in(days=2),
                                            "assignee_user_id": str(member.id)})  # fmt: skip
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["kind"] == "manual" and task["created_by_user_id"] == str(member.id)

    patch = f"{biz.base}/follow-ups/{task['id']}"
    r = await member.client.patch(patch, json={"assignee_user_id": None})
    assert r.status_code == 200 and r.json()["assignee_user_id"] is None
    r = await member.client.patch(patch, json={"status": "done"})
    assert r.json()["status"] == "done" and r.json()["completed_at"]
    r = await member.client.patch(patch, json={"status": "open"})
    assert r.json()["status"] == "open" and r.json()["completed_at"] is None
    assert [t["kind"] for t in await _tasks(member, biz, lead["id"])].count("manual") == 1


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"title": "x", "due_at": "2026-01-01T00:00:00+00:00"}, "invalid_due_at"),
        ({"title": "x", "due_at": "2030-01-01T10:00:00"}, None),  # no timezone
        ({"title": "   ", "due_at": "IN_A_DAY"}, "invalid_title"),
        ({"title": "x", "due_at": "IN_A_DAY", "assignee_user_id": str(uuid.uuid4())},
         "invalid_assignee"),
        ({"title": "x", "due_at": "IN_A_DAY", "extra": 1}, None),
    ],
)  # fmt: skip
async def test_invalid_tasks_are_rejected(
    harness: AppHarness, body: dict[str, Any], detail: str | None
) -> None:
    biz, lead, _ = await _lead(harness)
    if body.get("due_at") == "IN_A_DAY":
        body = body | {"due_at": _in(days=1)}
    r = await biz.owner.client.post(f"{biz.base}/leads/{lead['id']}/follow-ups", json=body)
    assert r.status_code == 422, r.text
    if detail:
        assert r.json()["detail"] == detail


async def test_open_task_limit(harness: AppHarness) -> None:
    biz, lead, _ = await _lead(harness)
    url = f"{biz.base}/leads/{lead['id']}/follow-ups"
    for i in range(follow_ups.MAX_OPEN_TASKS_PER_LEAD - 1):  # + the agent's first task
        r = await biz.owner.client.post(url, json={"title": f"t{i}", "due_at": _in(days=1)})
        assert r.status_code == 201, r.text
    r = await biz.owner.client.post(url, json={"title": "one too many", "due_at": _in(days=1)})
    assert r.status_code == 409 and r.json()["detail"] == "too_many_open_follow_ups"


async def _make_due(migrator_engine: AsyncEngine, task_id: str) -> None:
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text("UPDATE follow_up_tasks SET due_at = now() - interval '1 minute' WHERE id = :id"),
            {"id": task_id},
        )


async def test_due_task_reminds_owners_and_admins_once(
    harness: AppHarness, app_factory: Factory, settings: Settings,
    migrator_engine: AsyncEngine,
) -> None:  # fmt: skip
    biz, lead, _ = await _lead(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    (task,) = await _tasks(biz.owner, biz, lead["id"])
    await _make_due(migrator_engine, task["id"])

    before = len(harness.mailer.sent)
    assert await follow_ups.send_due_reminders(app_factory, settings, harness.mailer) >= 1
    sent = harness.mailer.sent[before:]
    assert sorted(m.to for m in sent) == sorted([biz.owner.email, admin.email])
    assert member.email not in [m.to for m in sent]
    assert all(m.subject == "Follow-up due: Contact Sara" and f"/leads/{lead['id']}" in m.body
               for m in sent)  # fmt: skip

    again = len(harness.mailer.sent)
    await follow_ups.send_due_reminders(app_factory, settings, harness.mailer)
    assert [m for m in harness.mailer.sent[again:] if m.to in (biz.owner.email, admin.email)] == []


async def test_assigned_task_reminds_only_the_assignee_and_retries_after_a_failure(
    harness: AppHarness, app_factory: Factory, settings: Settings,
    migrator_engine: AsyncEngine,
) -> None:  # fmt: skip
    biz, lead, _ = await _lead(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    r = await biz.owner.client.post(f"{biz.base}/leads/{lead['id']}/follow-ups", json={
        "title": "Call back", "due_at": _in(hours=2), "assignee_user_id": str(member.id)})  # fmt: skip
    task = r.json()
    await _make_due(migrator_engine, task["id"])

    harness.mailer.failing = True
    await follow_ups.send_due_reminders(app_factory, settings, harness.mailer)
    harness.mailer.failing = False
    before = len(harness.mailer.sent)
    await follow_ups.send_due_reminders(app_factory, settings, harness.mailer)
    mine = [m for m in harness.mailer.sent[before:] if m.subject == "Follow-up due: Call back"]
    assert [m.to for m in mine] == [member.email]


async def test_done_tasks_are_never_reminded(
    harness: AppHarness, app_factory: Factory, settings: Settings,
    migrator_engine: AsyncEngine,
) -> None:  # fmt: skip
    biz, lead, _ = await _lead(harness, name="Omar")
    (task,) = await _tasks(biz.owner, biz, lead["id"])
    await biz.owner.client.patch(f"{biz.base}/follow-ups/{task['id']}", json={"status": "done"})
    await _make_due(migrator_engine, task["id"])
    before = len(harness.mailer.sent)
    await follow_ups.send_due_reminders(app_factory, settings, harness.mailer)
    assert [m for m in harness.mailer.sent[before:] if "Contact Omar" in m.subject] == []


async def test_claim_function_refuses_bad_arguments(app_factory: Factory) -> None:
    async with app_factory() as session:
        with pytest.raises(Exception, match="invalid follow-up claim arguments"):
            await session.execute(text("SELECT * FROM agentree_claim_due_follow_ups(now(), 0)"))
