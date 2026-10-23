"""The Executive Assistant (Task 20): business state and checked numbers in its prompt; it only
proposes changes, which become approval requests (once / always allow) validated against this
business's real agents, leads and members; nothing runs without a current Owner or Admin."""

import json
from typing import Any

from agentree.agents.prompts import STATE_CLOSE, STATE_OPEN
from agentree.agents.service import UNVERIFIED_NUMBERS
from agentree.analytics import service as analytics
from tests.conftest import AppHarness
from tests.helpers import invite_and_join
from tests.test_agents import Biz, _configure, _fake, _say, _system
from tests.test_support_agents import SALES, _support_business, _visitor


async def _executive(h: AppHarness, **over: Any) -> Biz:
    biz = await _support_business(h)
    await _configure(biz, "executive", enabled=True, public=False, **over)
    return biz


async def _ask(biz: Biz, message: str, conv: str | None = None) -> dict[str, Any]:
    r = await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={
        "message": message, "agent": "executive", "conversation_id": conv})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _action(**params: Any) -> str:
    return f"<<ACTION {json.dumps(params)}>>"


async def _pending(biz: Biz) -> list[dict[str, Any]]:
    return (await biz.owner.client.get(f"{biz.base}/approvals")).json()  # type: ignore[no-any-return]


async def _agents(biz: Biz) -> dict[str, dict[str, Any]]:
    return {a["role"]: a for a in (await biz.owner.client.get(biz.agents)).json()}


async def _lead(h: AppHarness, biz: Biz, name: str = "Sara") -> dict[str, Any]:
    c, auth = await _visitor(h, biz)
    _fake(h).replies.append("Happy to help.")
    conv = (await _say(c, biz, auth, "Chairs?", agent=SALES)).json()["conversation_id"]
    r = await c.post(f"{biz.pub}/leads", headers=auth, json={
        "conversation_id": conv, "name": name, "email": f"{name.lower()}@example.com",
        "need": "Ten office chairs", "consent": True, "idempotency_key": f"k-{conv}"})  # fmt: skip
    assert r.status_code == 200, r.text
    return (await biz.owner.client.get(f"{biz.base}/leads")).json()["leads"][0]  # type: ignore[no-any-return]


def _label(lead: dict[str, Any]) -> str:
    return f"L-{lead['id'].replace('-', '')[-6:]}"


# --- availability and context ------------------------------------------------------------------


async def test_executive_is_internal_and_off_by_default(harness: AppHarness) -> None:
    biz = await _support_business(harness)
    executive = (await _agents(biz))["executive"]
    assert executive["available"] and not executive["enabled"]
    assert executive["available_tools"] == ["assign_lead", "set_agent_enabled",
                                            "update_lead_status", "update_public_profile"]  # fmt: skip
    await _configure(biz, "executive", enabled=True, public=False)
    c, auth = await _visitor(harness, biz)
    r = await _say(c, biz, auth, "Pause your agents", agent="executive")
    assert r.status_code == 422 and r.json()["detail"] == "invalid_agent"


async def test_prompt_holds_business_state_and_computed_numbers(harness: AppHarness) -> None:
    biz = await _executive(harness)
    lead = await _lead(harness, biz)
    await analytics.compute_due(harness.app.state.session_factory)
    _fake(harness).replies.append("You have 1 new lead.")
    body = await _ask(biz, "How are we doing?")
    assert body["agent"] == "executive" and body["reply"] == "You have 1 new lead."
    system = _system(harness)
    state = system.split(STATE_OPEN, 1)[1].split(STATE_CLOSE, 1)[0]
    assert "- sales (Sales Agent): on, open to visitors" in state
    assert "- technical_support (Technical Support): on, open to visitors" in state
    assert "executive (" not in state  # it never manages itself
    assert "Public page: on." in state
    assert (
        f"- {_label(lead)}: Sara, new, received " in state and "needs: Ten office chairs" in state
    )
    assert f"- {biz.owner.email} (owner)" in state and "Requests waiting for approval: 0" in state
    assert '<<ACTION {"action": "set_agent_enabled"' in state
    assert "<<<COMPUTED_NUMBERS" in system and "- New leads: 1" in system
    assert "Never say a change is done" in system

    # Numbers are checked as for the Data Analyst.
    _fake(harness).replies.append("You will close 12 deals this week.")
    reply = (await _ask(biz, "Forecast?", body["conversation_id"]))["reply"]
    assert reply.startswith(UNVERIFIED_NUMBERS) and "12 deals" not in reply


# --- proposals become approval requests --------------------------------------------------------


async def test_a_proposal_waits_for_approval_then_runs(harness: AppHarness) -> None:
    biz = await _executive(harness)
    _fake(harness).replies.append("I'll ask for approval.\n" + _action(
        action="set_agent_enabled", agent="technical_support", enabled=False))  # fmt: skip
    body = await _ask(biz, "Turn off Technical Support")
    assert body["reply"] == ("I'll ask for approval.\n\nWaiting for approval: Turn off the "
                             "Technical Support. An owner or admin can approve it on the "
                             "Approvals page.")  # fmt: skip
    assert (await _agents(biz))["technical_support"]["enabled"] is True  # nothing ran
    (pending,) = await _pending(biz)
    assert pending["agent"] == "executive" and pending["action"] == "set_agent_enabled"
    assert pending["params"] == {"agent": "technical_support", "enabled": False}

    r = await biz.owner.client.post(f"{biz.base}/approvals/{pending['id']}/decision",
                                    json={"decision": "once"})  # fmt: skip
    assert r.status_code == 200, r.text
    assert (await _agents(biz))["technical_support"]["enabled"] is False
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    change = next(e for e in events if e["action"] == "agent.config_updated"
                  and e["details"].get("agent") == "technical_support")  # fmt: skip
    assert change["actor"]["email"] == biz.owner.email  # the approver, not the AI

    # The stored reply keeps the status line (the conversation shows what was asked).
    conv = body["conversation_id"]
    messages = (await biz.owner.client.get(
        f"{biz.base}/conversations/{conv}/messages")).json()  # fmt: skip
    assert "Waiting for approval: Turn off the Technical Support." in messages[-1]["content"]
    assert "<<ACTION" not in messages[-1]["content"]


async def test_always_allow_runs_later_proposals_at_once(harness: AppHarness) -> None:
    biz = await _executive(harness)
    _fake(harness).replies.append(_action(action="set_agent_enabled", agent="technical_support",
                                          enabled=False))  # fmt: skip
    await _ask(biz, "Turn off Technical Support")
    (pending,) = await _pending(biz)
    await biz.owner.client.post(f"{biz.base}/approvals/{pending['id']}/decision",
                                json={"decision": "always"})  # fmt: skip
    _fake(harness).replies.append("Turning it back on.\n" + _action(
        action="set_agent_enabled", agent="technical_support", enabled=True))  # fmt: skip
    body = await _ask(biz, "Turn it back on")
    assert body["reply"].endswith("Done (always allowed): Turn on the Technical Support.")
    assert (await _agents(biz))["technical_support"]["enabled"] is True
    assert await _pending(biz) == []


async def test_a_members_proposals_wait_even_under_a_rule(harness: AppHarness) -> None:
    """Task 22 security review: a Member cannot use an Admin's "always allow" rule to make
    Admin-only changes through the Executive Assistant."""
    biz = await _executive(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    _fake(harness).replies.append(_action(action="set_agent_enabled", agent="technical_support",
                                          enabled=False))  # fmt: skip
    await _ask(biz, "Turn off Technical Support")
    (pending,) = await _pending(biz)
    await biz.owner.client.post(f"{biz.base}/approvals/{pending['id']}/decision",
                                json={"decision": "always"})  # fmt: skip
    _fake(harness).replies.append(_action(action="set_agent_enabled", agent="technical_support",
                                          enabled=True))  # fmt: skip
    r = await member.client.post(f"{biz.base}/agents/sales/console", json={
        "message": "Turn it back on", "agent": "executive"})  # fmt: skip
    assert r.status_code == 200, r.text
    assert "Waiting for approval: Turn on the Technical Support." in r.json()["reply"]
    assert (await _agents(biz))["technical_support"]["enabled"] is False
    (waiting,) = await _pending(biz)
    assert waiting["summary"] == "Turn on the Technical Support"


async def test_a_demoted_approver_no_longer_authorizes(harness: AppHarness) -> None:
    biz = await _executive(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    _fake(harness).replies.append(_action(action="set_agent_enabled", agent="technical_support",
                                          enabled=False))  # fmt: skip
    await _ask(biz, "Turn off Technical Support")
    (pending,) = await _pending(biz)
    r = await admin.client.post(f"{biz.base}/approvals/{pending['id']}/decision",
                                json={"decision": "always"})  # fmt: skip
    assert r.status_code == 200
    r = await biz.owner.client.patch(f"{biz.base}/members/{admin.id}", json={"role": "member"})
    assert r.status_code == 200, r.text
    # The rule the former admin created no longer lets anything run.
    _fake(harness).replies.append(_action(action="set_agent_enabled", agent="technical_support",
                                          enabled=True))  # fmt: skip
    body = await _ask(biz, "Turn it back on")
    assert body["reply"].endswith("Couldn't do it: Turn on the Technical Support.")
    assert (await _agents(biz))["technical_support"]["enabled"] is False
    history = (await biz.owner.client.get(f"{biz.base}/approvals?view=history")).json()
    assert history[0]["status"] == "canceled" and history[0]["error"] == "approver_not_allowed"


async def test_lead_status_and_assignment(harness: AppHarness) -> None:
    biz = await _executive(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    lead = await _lead(harness, biz)
    _fake(harness).replies.append("Done asking.\n" + _action(
        action="update_lead_status", lead=_label(lead), status="contacted") + "\n" + _action(
        action="assign_lead", lead=_label(lead), member=member.email))  # fmt: skip
    body = await _ask(biz, "Mark Sara contacted and give her to my colleague")
    assert "Waiting for approval: Move lead Sara to contacted." in body["reply"]
    assert f"Waiting for approval: Assign lead Sara to {member.email}." in body["reply"]
    for p in await _pending(biz):
        r = await biz.owner.client.post(f"{biz.base}/approvals/{p['id']}/decision",
                                        json={"decision": "once"})  # fmt: skip
        assert r.status_code == 200, r.text
    got = (await biz.owner.client.get(f"{biz.base}/leads/{lead['id']}")).json()
    assert got["status"] == "contacted"
    tasks = (await biz.owner.client.get(f"{biz.base}/leads/{lead['id']}/follow-ups")).json()
    assert tasks and all(t["assignee_user_id"] == str(member.id) for t in tasks
                         if t["status"] == "open")  # fmt: skip
    assert any(t["assignee_user_id"] == str(member.id) for t in tasks)


async def test_public_page_update(harness: AppHarness) -> None:
    biz = await _executive(harness)
    _fake(harness).replies.append(_action(action="update_public_profile", enabled=False,
                                          bio="Back on Monday"))  # fmt: skip
    body = await _ask(biz, "Close the public page and say we're back on Monday")
    assert "Waiting for approval: Turn the public page off and change its description." in (
        body["reply"])  # fmt: skip
    (pending,) = await _pending(biz)
    await biz.owner.client.post(f"{biz.base}/approvals/{pending['id']}/decision",
                                json={"decision": "once"})  # fmt: skip
    profile = (await biz.owner.client.get(f"{biz.base}/public-profile")).json()
    assert profile["enabled"] is False and profile["bio"] == "Back on Monday"


async def test_invalid_or_disallowed_proposals_never_become_requests(harness: AppHarness) -> None:
    biz = await _executive(harness)
    await _lead(harness, biz)
    bad = [
        _action(action="set_agent_enabled", agent="executive", enabled=False),  # itself
        _action(action="set_agent_enabled", agent="cfo", enabled=False),
        _action(action="update_lead_status", lead="L-000000", status="won"),
        _action(action="delete_everything"),
    ]
    _fake(harness).replies.append("\n".join(bad))
    body = await _ask(biz, "Do things")
    assert body["reply"].count("I couldn't prepare that change") == 3  # at most 3 per reply
    assert "unknown agent" in body["reply"] and "unknown lead" in body["reply"]
    assert await _pending(biz) == []

    _fake(harness).replies.append("<<ACTION not json>> Sure." + _action(
        action="assign_lead", lead="L-zzz", member="stranger@example.com"))  # fmt: skip
    body = await _ask(biz, "Assign it", body["conversation_id"])
    assert "<<ACTION" not in body["reply"] and "unknown lead" in body["reply"]
    assert await _pending(biz) == []

    # The business can take a tool away: proposals for it are refused.
    tools = ["assign_lead", "update_lead_status", "update_public_profile"]
    await _configure(biz, "executive", enabled=True, public=False, tools=tools)
    _fake(harness).replies.append(_action(action="set_agent_enabled", agent="sales",
                                          enabled=False))  # fmt: skip
    body = await _ask(biz, "Turn off sales", body["conversation_id"])
    assert body["reply"] == "I'm not allowed to make that change in this business."
    assert await _pending(biz) == []


async def test_other_agents_cannot_propose(harness: AppHarness) -> None:
    biz = await _executive(harness)
    _fake(harness).replies.append(
        "Sure!\n" + _action(action="set_agent_enabled", agent="technical_support", enabled=False)
    )
    r = await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={
        "message": "Turn off support", "agent": "sales"})  # fmt: skip
    assert r.json()["reply"] == "Sure!"  # the marker is dropped, nothing is requested
    assert await _pending(biz) == []


async def test_the_console_cannot_answer_into_a_visitor_conversation(harness: AppHarness) -> None:
    """Task 22 security review: internal agents (the Executive's business state) must never
    reply into a thread the visitor can read; visitor conversations are answered in the Inbox."""
    biz = await _executive(harness)
    c, auth = await _visitor(harness, biz)
    _fake(harness).replies.append("Hello!")
    conv = (await _say(c, biz, auth, "Hi", agent=SALES)).json()["conversation_id"]
    r = await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={
        "message": "Who is on the team?", "agent": "executive", "conversation_id": conv})  # fmt: skip
    assert r.status_code == 404
    seen = (await c.get(f"{biz.pub}/conversations/{conv}/messages", headers=auth)).json()
    assert [m["content"] for m in seen] == ["Hi", "Hello!"]
