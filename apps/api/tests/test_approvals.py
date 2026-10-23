"""Approvals (Task 19): the Sales Agent's follow-up email drafts wait for an Owner or Admin, who
approves once, always allows, edits or rejects; exactly-once execution, expiry, voided
approvals, flagged drafts, rules, notifications, audit, purge and permissions."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agentree.actions import service as gateway
from agentree.actions.service import Action
from agentree.approvals import service as approvals
from agentree.core.config import Settings
from agentree.leads import follow_ups, outreach
from agentree.tenancy.context import TenantContext, TenantSource
from tests.conftest import AppHarness
from tests.helpers import invite_and_join
from tests.test_agents import _fake
from tests.test_follow_ups import Biz, _lead, _make_due, _tasks

Factory = async_sessionmaker[AsyncSession]
TOOLS = ["create_lead", "update_lead", "create_follow_up_task"]
DRAFT = {"subject": "Following up on your chair request",
         "body": "Hi Sara,\n\nThanks for asking about our office chairs. We'd love to help you "
                 "pick the right one. Reply to this email and we'll take it from there.\n\n"
                 "The Maple Chairs team"}  # fmt: skip


async def _follow_up_emails(biz: Biz, *, on: bool = True) -> None:
    tools = TOOLS + (["send_follow_up_email"] if on else [])
    r = await biz.owner.client.put(f"{biz.base}/agents/sales", json={
        "enabled": True, "display_name": "", "public": True, "tools": tools})  # fmt: skip
    assert r.status_code == 200, r.text


def _ctx(biz: Biz) -> TenantContext:
    return TenantContext(uuid.UUID(biz.id), TenantSource.JOB)


def _deps(h: AppHarness) -> approvals.Deps:
    return approvals.Deps(h.app.state.settings, h.mailer, h.push)


async def _confirm_email(migrator_engine: AsyncEngine, biz: Biz, email: str) -> None:
    """A verified customer profile for `email`, as the identity code flow leaves it."""
    async with migrator_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO customer_profiles (id, business_id, email, verified_at, created_at, "
            "last_seen_at) VALUES (:id, :b, :e, now(), now(), now()) ON CONFLICT DO NOTHING"),
            {"id": uuid.uuid4(), "b": biz.id, "e": email})  # fmt: skip


async def _due_draft(
    h: AppHarness, migrator_engine: AsyncEngine, settings: Settings, biz: Biz,
    lead: dict[str, Any], draft: dict[str, str] | str = DRAFT, *, confirmed: bool = True,
) -> int:  # fmt: skip
    """Make the lead's first-contact task due and run the reminders job with drafting on.
    `confirmed`: the visitor proved the lead's address with a code (else drafts are flagged)."""
    if confirmed:
        await _confirm_email(migrator_engine, biz, lead["email"])
    (task,) = await _tasks(biz.owner, biz, lead["id"])
    await _make_due(migrator_engine, task["id"])
    _fake(h).replies.append(draft if isinstance(draft, str) else json.dumps(draft))
    factory = h.app.state.session_factory
    hook = outreach.first_contact_hook(factory, h.app.state.vault, _deps(h),
                                       h.app.state.llm_providers)  # fmt: skip
    before = len(h.mailer.sent)
    await follow_ups.send_due_reminders(factory, settings, h.mailer, on_first_contact=hook)
    return before


async def _pending(biz: Biz) -> list[dict[str, Any]]:
    r = await biz.owner.client.get(f"{biz.base}/approvals")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _decide(biz: Biz, approval_id: str, decision: str, **extra: Any) -> Any:
    return await biz.owner.client.post(f"{biz.base}/approvals/{approval_id}/decision",
                                       json={"decision": decision, **extra})  # fmt: skip


def _to(h: AppHarness, address: str, since: int = 0) -> list[Any]:
    return [m for m in h.mailer.sent[since:] if m.to == address]


# --- the follow-up email tool ------------------------------------------------------------------


async def test_follow_up_emails_are_opt_in(harness: AppHarness) -> None:
    biz, _lead_row, _ = await _lead(harness)
    sales = next(a for a in (await biz.owner.client.get(f"{biz.base}/agents")).json()
                 if a["role"] == "sales")  # fmt: skip
    assert "send_follow_up_email" in sales["available_tools"]
    assert "send_follow_up_email" not in sales["tools"]


async def test_tool_off_keeps_the_plain_reminder(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    before = await _due_draft(harness, migrator_engine, settings, biz, lead)
    assert [m.subject for m in _to(harness, biz.owner.email, before)] == [
        "Follow-up due: Contact Sara"]  # fmt: skip
    assert await _pending(biz) == []


def test_every_sensitive_action_has_an_executor() -> None:
    assert approvals.registered() == frozenset(gateway.APPROVALS)


async def test_the_gateway_never_runs_a_sensitive_action_directly(harness: AppHarness) -> None:
    biz, _lead_row, _ = await _lead(harness)
    async with harness.app.state.session_factory() as session, session.begin():
        with pytest.raises(gateway.ActionDeniedError, match="needs an approval"):
            await gateway.claim(session, _ctx(biz), agent="sales",
                                action=Action.SEND_FOLLOW_UP_EMAIL, idempotency_key="k",
                                params={})  # fmt: skip


# --- approve once -------------------------------------------------------------------------------


async def test_draft_waits_for_approval_then_sends_exactly_once(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    await _follow_up_emails(biz)
    before = await _due_draft(harness, migrator_engine, settings, biz, lead)

    # Owners and admins are asked (no separate reminder); the lead hears nothing yet.
    sent = harness.mailer.sent[before:]
    assert sorted(m.to for m in sent) == sorted([biz.owner.email, admin.email])
    assert all(m.subject == "Approval needed: Sales Agent wants to send a follow-up email to a "
               "lead" and "/approvals" in m.body for m in sent)  # fmt: skip
    assert all(DRAFT["subject"] not in m.body for m in sent)  # the draft stays in Agentree
    assert _to(harness, "s@example.com") == []
    system = _fake(harness).calls[-1][1].messages[0].content
    assert "Write a short follow-up email" in system and "<<<BUSINESS_KNOWLEDGE" in system

    (pending,) = await _pending(biz)
    assert pending["status"] == "pending" and pending["agent"] == "sales"
    assert pending["action"] == "send_follow_up_email" and pending["summary"] == (
        "Follow-up email to Sara")  # fmt: skip
    assert pending["params"] == {"lead_id": lead["id"], "to": "s@example.com", **DRAFT}
    assert pending["flag"] is None and pending["allow_always"] and pending["editable"]

    # Members may look, not decide.
    url = f"{biz.base}/approvals/{pending['id']}/decision"
    r = await member.client.post(url, json={"decision": "once"})
    assert r.status_code == 403
    assert (await member.client.get(f"{biz.base}/approvals")).json()[0]["id"] == pending["id"]

    r = await _decide(biz, pending["id"], "once")
    assert r.status_code == 200 and r.json()["decision"] == "once", r.text
    (email,) = _to(harness, "s@example.com")
    assert email.subject == DRAFT["subject"] and "pick the right one" in email.body
    assert email.reply_to == biz.owner.email  # replies reach the approver
    assert "you asked Maple Chairs to contact you" in email.body
    done = (await biz.owner.client.get(f"{biz.base}/approvals/{pending['id']}")).json()
    assert done["status"] == "executed" and done["decided_by_user_id"] == str(biz.owner.id)

    # Never twice: deciding again, the worker's safety net, concurrent runners.
    assert (await _decide(biz, pending["id"], "once")).status_code == 409
    await approvals.run_due(harness.app.state.session_factory, _deps(harness))
    factory, ctx = harness.app.state.session_factory, _ctx(biz)
    await asyncio.gather(*(approvals.execute(factory, ctx, _deps(harness),
                                             uuid.UUID(pending["id"])) for _ in range(3)))  # fmt: skip
    assert len(_to(harness, "s@example.com")) == 1
    assert await _pending(biz) == []
    history = (await biz.owner.client.get(f"{biz.base}/approvals?view=history")).json()
    assert [h["id"] for h in history] == [pending["id"]]

    actions = [e["action"] for e in (await biz.owner.client.get(
        f"{biz.base}/audit-events")).json()["events"]]  # fmt: skip
    for a in ("approval.requested", "approval.decided", "approval.executed"):
        assert a in actions


async def test_concurrent_approved_runs_send_once(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    factory, ctx = harness.app.state.session_factory, _ctx(biz)
    await approvals.decide(factory, ctx, uuid.UUID(pending["id"]), actor_id=biz.owner.id,
                           decision="once")  # fmt: skip
    results = await asyncio.gather(*(approvals.execute(factory, ctx, _deps(harness),
                                                       uuid.UUID(pending["id"]))
                                     for _ in range(4)))  # fmt: skip
    assert results.count("executed") == 1
    assert len(_to(harness, "s@example.com")) == 1


# --- always allow -------------------------------------------------------------------------------


async def test_always_allow_sends_later_drafts_without_asking_until_revoked(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (first,) = await _pending(biz)
    r = await _decide(biz, first["id"], "always")
    assert r.status_code == 200 and r.json()["decision"] == "always"
    (rule,) = (await biz.owner.client.get(f"{biz.base}/approval-rules")).json()
    assert rule["agent"] == "sales" and rule["action"] == "send_follow_up_email"

    # A second lead: sent right away, nobody is asked; replies go to who allowed it.
    lead2 = await _second_lead(harness, biz, "Omar", "o@example.com")
    before = await _due_draft(harness, migrator_engine, settings, biz, lead2)
    (email,) = _to(harness, "o@example.com")
    assert email.reply_to == biz.owner.email
    assert [m for m in harness.mailer.sent[before:] if m.to == biz.owner.email] == []
    history = (await biz.owner.client.get(f"{biz.base}/approvals?view=history")).json()
    assert history[0]["decision"] == "rule" and history[0]["status"] == "executed"
    assert await _pending(biz) == []

    # Revoked: the next draft waits for a person again.
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    assert (await member.client.delete(
        f"{biz.base}/approval-rules/{rule['id']}")).status_code == 403  # fmt: skip
    assert (await biz.owner.client.delete(
        f"{biz.base}/approval-rules/{rule['id']}")).status_code == 204  # fmt: skip
    lead3 = await _second_lead(harness, biz, "Lina", "l@example.com")
    await _due_draft(harness, migrator_engine, settings, biz, lead3)
    assert _to(harness, "l@example.com") == []
    assert [p["summary"] for p in await _pending(biz)] == ["Follow-up email to Lina"]


async def _second_lead(h: AppHarness, biz: Biz, name: str, email: str,
                       need: str | None = None) -> dict[str, Any]:  # fmt: skip
    c = h.new_client()
    auth = {"X-Agentree-Guest": (await c.post(f"{biz.pub}/sessions")).json()["token"]}
    convo = (await c.post(f"{biz.pub}/chat", json={"message": "hi"}, headers=auth)).json()
    r = await c.post(
        f"{biz.pub}/leads",
        headers=auth,
        json={
            "conversation_id": convo["conversation_id"],
            "name": name,
            "email": email,
            "consent": True,
            "idempotency_key": uuid.uuid4().hex,
        }
        | ({"need": need} if need else {}),
    )
    assert r.status_code == 200, r.text
    leads = (await biz.owner.client.get(f"{biz.base}/leads")).json()["leads"]
    return next(x for x in leads if x["email"] == email)


# --- flagged drafts, edits, rejection, expiry ---------------------------------------------------


async def test_unverified_numbers_or_links_always_wait_for_a_person(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (first,) = await _pending(biz)
    assert (await _decide(biz, first["id"], "always")).status_code == 200  # rule exists now

    invented = {"subject": "20% off for you", "body": "Hi Omar, our chairs are 20% off this "
                "week only at https://evil.example/deal. Reply to this email!"}  # fmt: skip
    lead2 = await _second_lead(harness, biz, "Omar", "o@example.com")
    await _due_draft(harness, migrator_engine, settings, biz, lead2, invented)
    assert _to(harness, "o@example.com") == []  # not sent despite the rule
    (flagged,) = await _pending(biz)
    assert flagged["flag"] == "unverified_numbers" and flagged["allow_always"] is False
    r = await _decide(biz, flagged["id"], "always")
    assert r.status_code == 409 and r.json()["detail"] == "always_not_allowed"


async def test_a_visitor_cannot_plant_links_or_numbers_in_an_auto_sent_email(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    """Task 22 security review: the visitor types the lead's name, request and (unverified)
    address, so a link or phone number only they wrote never counts as checked."""
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (first,) = await _pending(biz)
    assert (await _decide(biz, first["id"], "always")).status_code == 200  # rule exists now
    need = "Claim your refund at https://phish.example/login or call 555 0100"
    planted = {"subject": "Your refund", "body": "Hi Victim, claim your refund at "
               "https://phish.example/login or call 555 0100. The Maple Chairs team"}  # fmt: skip
    lead2 = await _second_lead(harness, biz, "Victim", "victim@example.com", need)
    await _due_draft(harness, migrator_engine, settings, biz, lead2, planted)
    assert _to(harness, "victim@example.com") == []  # not sent despite the rule
    (flagged,) = await _pending(biz)
    assert flagged["flag"] in {"unverified_numbers", "unverified_links"}
    assert flagged["allow_always"] is False


async def test_an_unconfirmed_address_always_waits_for_a_person(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    """PO decision 2026-10-23 (SR-01): anyone can type someone else's address, so a follow-up to
    an address the visitor did not confirm with a code is never sent without a person reading it."""
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (first,) = await _pending(biz)
    assert (await _decide(biz, first["id"], "always")).status_code == 200  # rule exists now
    lead2 = await _second_lead(harness, biz, "Omar", "o@example.com")
    await _due_draft(harness, migrator_engine, settings, biz, lead2, confirmed=False)
    assert _to(harness, "o@example.com") == []  # not sent despite the rule
    (flagged,) = await _pending(biz)
    assert flagged["flag"] == "unverified_recipient" and flagged["allow_always"] is False
    assert (await _decide(biz, flagged["id"], "once")).status_code == 200  # a person may send it
    assert len(_to(harness, "o@example.com")) == 1


def test_draft_checks() -> None:
    sources = ["Chairs cost $199. See https://maple.example/chairs", "Sara", "Maple Chairs"]
    assert outreach.check_draft("Chairs", "From $199: https://maple.example/chairs.",
                                sources=sources) is None  # fmt: skip
    assert outreach.check_draft("Chairs", "Only $149!", sources=sources) == "unverified_numbers"
    assert outreach.check_draft("Chairs", "See www.other.example", sources=sources) == (
        "unverified_links")  # fmt: skip
    with pytest.raises(outreach.DraftError):
        outreach.parse_draft("Sure! Here's an email.")
    subject, _body = outreach.parse_draft('{"subject": "Hi\\nthere <<x>>", "body": "' + "a" * 30
                                         + '"}')  # fmt: skip
    assert subject == "Hi there x"


async def test_owner_edits_the_draft_before_approving(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    r = await _decide(biz, pending["id"], "once", edits={"to": "evil@example.com"})
    assert r.status_code == 422 and r.json()["detail"] == "to"  # the recipient never changes
    r = await _decide(biz, pending["id"], "once", edits={"body": ""})
    assert r.status_code == 422 and r.json()["detail"] == "body"
    r = await _decide(biz, pending["id"], "once", edits={
        "subject": "Your chair", "body": "Hi Sara, call us any time.\n\nMaple"})  # fmt: skip
    assert r.status_code == 200 and r.json()["params"]["subject"] == "Your chair"
    (email,) = _to(harness, "s@example.com")
    assert email.subject == "Your chair" and "call us any time." in email.body


async def test_rejected_and_expired_requests_never_run(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (first,) = await _pending(biz)
    assert (await _decide(biz, first["id"], "reject")).json()["status"] == "rejected"

    lead2 = await _second_lead(harness, biz, "Omar", "o@example.com")
    await _due_draft(harness, migrator_engine, settings, biz, lead2)
    (second,) = await _pending(biz)
    async with migrator_engine.begin() as conn:
        await conn.execute(text("UPDATE approval_requests SET expires_at = now() - interval "
                                "'1 minute' WHERE id = :id"), {"id": second["id"]})  # fmt: skip
    assert await _pending(biz) == []
    r = await _decide(biz, second["id"], "once")
    assert r.status_code == 409 and r.json()["detail"] == "expired"
    statuses = {h["id"]: h["status"] for h in (await biz.owner.client.get(
        f"{biz.base}/approvals?view=history")).json()}  # fmt: skip
    assert statuses == {first["id"]: "rejected", second["id"]: "expired"}
    await approvals.run_due(harness.app.state.session_factory, _deps(harness))
    assert _to(harness, "s@example.com") == [] and _to(harness, "o@example.com") == []


# --- checks at execution time -------------------------------------------------------------------


async def test_approval_is_void_when_things_changed(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    factory, ctx, aid = harness.app.state.session_factory, _ctx(biz), uuid.UUID(pending["id"])

    # Parameters changed after the approval (not through an edit): voided.
    await approvals.decide(factory, ctx, aid, actor_id=biz.owner.id, decision="once")
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE approval_requests SET params = jsonb_set(params, "
                "'{body}', '\"Buy now!\"') WHERE id = :id"
            ),
            {"id": str(aid)},
        )
    assert await approvals.execute(factory, ctx, _deps(harness), aid) == "failed"
    got = await approvals.get_request(factory, ctx, aid)
    assert got.error == "params_changed" and _to(harness, "s@example.com") == []


@pytest.mark.parametrize("change", ["contacted", "tool_off"])
async def test_nothing_is_sent_when_no_longer_wanted(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings, change: str
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    if change == "contacted":  # the team reached the lead meanwhile
        r = await biz.owner.client.patch(f"{biz.base}/leads/{lead['id']}",
                                         json={"status": "contacted"})  # fmt: skip
        assert r.status_code == 200
    else:
        await _follow_up_emails(biz, on=False)
    r = await _decide(biz, pending["id"], "once")
    assert r.status_code == 200
    got = (await biz.owner.client.get(f"{biz.base}/approvals/{pending['id']}")).json()
    assert got["status"] == "canceled"
    assert got["error"] == ("lead_contacted" if change == "contacted" else "tool_turned_off")
    assert _to(harness, "s@example.com") == []


async def test_a_run_that_stopped_midway_is_unknown_and_never_retried(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    async with migrator_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE approval_requests SET status = 'executing', decision = "
                "'once', approved_hash = params_hash, started_at = now() - "
                "interval '11 minutes' WHERE id = :id"
            ),
            {"id": pending["id"]},
        )
    await approvals.run_due(harness.app.state.session_factory, _deps(harness))
    got = (await biz.owner.client.get(f"{biz.base}/approvals/{pending['id']}")).json()
    assert got["status"] == "unknown" and _to(harness, "s@example.com") == []


async def test_failed_draft_falls_back_to_the_reminder(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    before = await _due_draft(harness, migrator_engine, settings, biz, lead, "Sorry, no JSON")
    assert [m.subject for m in _to(harness, biz.owner.email, before)] == [
        "Follow-up due: Contact Sara"]  # fmt: skip
    assert await _pending(biz) == []


async def test_failed_send_is_recorded(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    harness.mailer.failing = True
    try:
        await _decide(biz, pending["id"], "once")
    finally:
        harness.mailer.failing = False
    got = (await biz.owner.client.get(f"{biz.base}/approvals/{pending['id']}")).json()
    assert got["status"] == "failed" and got["error"] == "send_failed"


# --- retention ----------------------------------------------------------------------------------


async def test_requests_are_purged_after_30_days(
    harness: AppHarness, migrator_engine: AsyncEngine, settings: Settings
) -> None:
    biz, lead, _ = await _lead(harness)
    await _follow_up_emails(biz)
    await _due_draft(harness, migrator_engine, settings, biz, lead)
    (pending,) = await _pending(biz)
    factory = harness.app.state.session_factory
    with pytest.raises(Exception, match="at least one day in the past"):
        async with factory() as session, session.begin():
            await session.execute(text("SELECT agentree_purge_approvals(now())"))
    async with migrator_engine.begin() as conn:
        await conn.execute(text("UPDATE approval_requests SET requested_at = now() - interval "
                                "'31 days' WHERE id = :id"), {"id": pending["id"]})  # fmt: skip
    await approvals.run_due(factory, _deps(harness))
    r = await biz.owner.client.get(f"{biz.base}/approvals/{pending['id']}")
    assert r.status_code == 404
