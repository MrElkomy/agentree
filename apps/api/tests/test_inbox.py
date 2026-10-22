"""Human inbox: the AI hands a visitor to the team, a member takes over, replies and hands back."""

import uuid
from typing import Any

from httpx import AsyncClient

from agentree.agents.prompts import take_handoff_marker
from agentree.llm.base import ProviderName
from agentree.llm.fake import FakeProvider
from tests.conftest import AppHarness
from tests.helpers import Account, create_business, invite_and_join, signup

KEY = "sk-inbox-primary-key-eeee5555"  # gitleaks:allow (fake test key)


class Biz:
    def __init__(self, owner: Account, business: dict[str, Any]) -> None:
        self.owner, self.id, self.slug = owner, business["id"], business["slug"]
        self.base = f"/api/businesses/{self.id}"
        self.inbox = f"{self.base}/inbox"
        self.pub = f"/api/public/{self.slug}"


async def _business(h: AppHarness) -> Biz:
    owner = await signup(h)
    biz = Biz(owner, await create_business(owner, "Cedar Desks"))
    r = await owner.client.put(f"{biz.base}/ai-providers/primary", json={
        "provider": "openai", "model": "gpt-4o-mini", "api_key": KEY, "verify": False})  # fmt: skip
    assert r.status_code == 200, r.text
    r = await owner.client.put(f"{biz.base}/public-profile", json={"enabled": True})
    assert r.status_code == 200, r.text
    return biz


def _fake(h: AppHarness) -> FakeProvider:
    return h.llm[ProviderName.OPENAI]


async def _guest(c: AsyncClient, biz: Biz) -> dict[str, str]:
    r = await c.post(f"{biz.pub}/sessions")
    assert r.status_code == 201, r.text
    return {"X-Agentree-Guest": r.json()["token"]}


async def _chat(
    h: AppHarness, biz: Biz, c: AsyncClient, auth: dict[str, str], message: str = "Hi there",
    reply: str = "Hello! How can I help?", conversation_id: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    _fake(h).replies.append(reply)
    body = {"message": message, "conversation_id": conversation_id}
    r = await c.post(f"{biz.pub}/chat", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _visitor(h: AppHarness, biz: Biz) -> tuple[AsyncClient, dict[str, str], str]:
    c = h.new_client()
    auth = await _guest(c, biz)
    return c, auth, (await _chat(h, biz, c, auth))["conversation_id"]


async def _events(acc: Account, biz: Biz) -> list[dict[str, Any]]:
    r = await acc.client.get(f"{biz.base}/audit-events")
    assert r.status_code == 200, r.text
    return r.json()["events"]  # type: ignore[no-any-return]


# --- marker ---------------------------------------------------------------------------------


def test_handoff_marker_is_stripped() -> None:
    assert take_handoff_marker("Connecting you now.\n<<HANDOFF>>") == ("Connecting you now.", True)
    assert take_handoff_marker("Plain reply") == ("Plain reply", False)


# --- the agent or the visitor asks for a person ---------------------------------------------


async def test_agent_handoff_pauses_the_ai_and_alerts_owners_and_admins(
    harness: AppHarness,
) -> None:
    biz = await _business(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    c = harness.new_client()
    auth = await _guest(c, biz)
    sent_before = len(harness.mailer.sent)
    out = await _chat(harness, biz, c, auth, message="Can I talk to a real person?",
                      reply="Sure, I'll connect you with the team.\n<<HANDOFF>>")  # fmt: skip
    assert out["status"] == "needs_human"
    assert out["reply"] == "Sure, I'll connect you with the team."
    conv_id = out["conversation_id"]

    alerts = harness.mailer.sent[sent_before:]
    assert sorted(m.to for m in alerts) == sorted([biz.owner.email, admin.email])
    assert member.email not in [m.to for m in alerts]
    assert all(m.html and f"/inbox/{conv_id}" in m.body for m in alerts)
    assert all("real person" not in m.body for m in alerts)  # no message content in emails

    # While waiting, the AI stays silent: visitor messages are stored, no provider call.
    calls = len(_fake(harness).calls)
    r = await c.post(f"{biz.pub}/chat", json={"message": "Hello?", "conversation_id": conv_id},
                     headers=auth)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "" and r.json()["status"] == "needs_human"
    assert len(_fake(harness).calls) == calls
    assert len(harness.mailer.sent) == sent_before + 2  # no second alert

    page = (await biz.owner.client.get(biz.inbox, params={"status": "needs_human"})).json()
    assert [i["id"] for i in page["items"]] == [conv_id]
    item = page["items"][0]
    assert item["handoff_reason"] == "agent" and item["preview"] == "Hello?"
    assert item["preview_role"] == "user"
    assert page["counts"]["needs_human"] == 1

    events = [e for e in await _events(biz.owner, biz)
              if e["action"] == "conversation.handoff_requested"]  # fmt: skip
    assert len(events) == 1 and events[0]["actor"] is None
    assert events[0]["details"] == {"channel": "public", "reason": "agent", "agent": "sales"}


async def test_visitor_requests_and_cancels_a_handoff(harness: AppHarness) -> None:
    biz = await _business(harness)
    c, auth, conv_id = await _visitor(harness, biz)
    url = f"{biz.pub}/conversations/{conv_id}/handoff"
    sent = len(harness.mailer.sent)

    r = await c.post(url, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "needs_human"
    assert len(harness.mailer.sent) == sent + 1  # the owner
    r = await c.post(url, headers=auth)  # repeated: no second alert
    assert r.status_code == 200 and len(harness.mailer.sent) == sent + 1

    r = await c.delete(url, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "open"
    out = await _chat(
        harness, biz, c, auth, message="Ok, question", reply="Sure.", conversation_id=conv_id
    )
    assert out["status"] == "open" and out["reply"] == "Sure."

    actions = [e["action"] for e in await _events(biz.owner, biz)]
    assert "conversation.handoff_canceled" in actions


async def test_guest_cannot_touch_another_guests_conversation(harness: AppHarness) -> None:
    biz = await _business(harness)
    _, _, conv_id = await _visitor(harness, biz)
    other = harness.new_client()
    other_auth = await _guest(other, biz)
    base = f"{biz.pub}/conversations/{conv_id}"
    assert (await other.get(base, headers=other_auth)).status_code == 404
    assert (await other.post(f"{base}/handoff", headers=other_auth)).status_code == 404
    assert (await other.delete(f"{base}/handoff", headers=other_auth)).status_code == 404
    assert (await other.post(f"{base}/handoff")).status_code in (401, 404)
    random = f"{biz.pub}/conversations/{uuid.uuid4()}"
    assert (await other.get(random, headers=other_auth)).status_code == 404


async def test_guest_of_another_business_cannot_use_the_conversation(harness: AppHarness) -> None:
    a = await _business(harness)
    b = await _business(harness)
    _, _, conv_id = await _visitor(harness, b)
    c = harness.new_client()
    auth = await _guest(c, a)
    r = await c.post(f"{a.pub}/conversations/{conv_id}/handoff", headers=auth)
    assert r.status_code == 404
    page = (await b.owner.client.get(b.inbox, params={"status": "needs_human"})).json()
    assert page["items"] == []


# --- the team takes over --------------------------------------------------------------------


async def test_take_over_reply_hand_back_and_resolve(harness: AppHarness) -> None:
    biz = await _business(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    c, auth, conv_id = await _visitor(harness, biz)
    await c.post(f"{biz.pub}/conversations/{conv_id}/handoff", headers=auth)
    url = f"{biz.inbox}/{conv_id}"

    # Replying needs a take-over first.
    r = await member.client.post(f"{url}/reply", json={"content": "Hi!"})
    assert r.status_code == 409 and r.json()["detail"] == "conversation_state"

    assert (await member.client.post(f"{url}/take-over")).status_code == 204
    convo = (await member.client.get(url)).json()["conversation"]
    assert convo["status"] == "human_active"
    assert convo["assignee_user_id"] == str(member.id)

    r = await member.client.post(f"{url}/reply", json={"content": "Hi, this is Lina from Cedar."})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "human" and r.json()["author_user_id"] == str(member.id)
    assert (await member.client.post(f"{url}/reply", json={"content": " "})).status_code == 422

    # The visitor sees the team's reply; the AI is still silent.
    seen = (await c.get(f"{biz.pub}/conversations/{conv_id}", headers=auth)).json()
    assert seen["status"] == "human_active"
    assert seen["messages"][-1] == {**seen["messages"][-1], "role": "human",
                                    "content": "Hi, this is Lina from Cedar."}  # fmt: skip
    assert "author_user_id" not in seen["messages"][-1]  # members stay anonymous to visitors
    calls = len(_fake(harness).calls)
    r = await c.post(f"{biz.pub}/chat", headers=auth,
                     json={"message": "Thanks Lina", "conversation_id": conv_id})  # fmt: skip
    assert r.json() == {**r.json(), "reply": "", "status": "human_active"}
    assert len(_fake(harness).calls) == calls

    roles = [m["role"] for m in (await member.client.get(url)).json()["messages"]]
    assert roles == ["user", "assistant", "human", "user"]
    msgs = (await member.client.get(url)).json()["messages"]
    assert msgs[2]["author_user_id"] == str(member.id)

    # Visitor cannot cancel once a person is active.
    r = await c.delete(f"{biz.pub}/conversations/{conv_id}/handoff", headers=auth)
    assert r.json()["status"] == "human_active"

    # Hand back to the AI: the next visitor message gets an AI reply that sees the team's turn.
    assert (await member.client.post(f"{url}/release")).status_code == 204
    convo = (await member.client.get(url)).json()["conversation"]
    assert convo["status"] == "open" and convo["assignee_user_id"] is None
    assert (await member.client.post(f"{url}/release")).status_code == 409
    out = await _chat(
        harness, biz, c, auth, message="One more thing", reply="Of course.", conversation_id=conv_id
    )
    assert out["reply"] == "Of course." and out["status"] == "open"
    history = _fake(harness).calls[-1][1].messages
    assert any(m.role == "assistant" and "Hi, this is Lina" in m.content for m in history)

    # Resolve, then a new visitor message reopens it for the AI.
    assert (await member.client.post(f"{url}/resolve")).status_code == 204
    assert (await member.client.get(url)).json()["conversation"]["status"] == "resolved"
    out = await _chat(
        harness, biz, c, auth, message="Back again", reply="Welcome back.", conversation_id=conv_id
    )
    assert out["status"] == "open" and out["reply"] == "Welcome back."

    events = await _events(biz.owner, biz)
    actions = {e["action"] for e in events}
    assert {"conversation.taken_over", "conversation.released",
            "conversation.resolved"} <= actions  # fmt: skip
    taken = next(e for e in events if e["action"] == "conversation.taken_over")
    assert taken["actor"] is not None
    assert "Lina" not in str(events) and "Thanks" not in str(events)


async def test_assign_requires_a_member_of_the_business(harness: AppHarness) -> None:
    biz = await _business(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    outsider = await signup(harness)
    _, _, conv_id = await _visitor(harness, biz)
    url = f"{biz.inbox}/{conv_id}/assign"

    r = await biz.owner.client.post(url, json={"assignee_user_id": str(outsider.id)})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_assignee"
    r = await biz.owner.client.post(url, json={"assignee_user_id": str(member.id)})
    assert r.status_code == 204, r.text
    item = (await biz.owner.client.get(f"{biz.inbox}/{conv_id}")).json()["conversation"]
    assert item["assignee_user_id"] == str(member.id)
    r = await biz.owner.client.post(url, json={"assignee_user_id": None})
    assert r.status_code == 204
    assigned = [e for e in await _events(biz.owner, biz) if e["action"] == "conversation.assigned"]
    assert len(assigned) == 2


async def test_inbox_lists_only_public_conversations_with_counts(harness: AppHarness) -> None:
    biz = await _business(harness)
    _fake(harness).replies.append("console reply")
    r = await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={"message": "hi"})
    assert r.status_code == 200
    console_id = r.json()["conversation_id"]
    _, _, first = await _visitor(harness, biz)
    c, auth, second = await _visitor(harness, biz)
    await c.post(f"{biz.pub}/conversations/{second}/handoff", headers=auth)

    page = (await biz.owner.client.get(biz.inbox)).json()
    assert [i["id"] for i in page["items"]] == [second, first]
    assert page["counts"] == {"open": 1, "needs_human": 1, "human_active": 0, "resolved": 0}
    assert (await biz.owner.client.get(f"{biz.inbox}/{console_id}")).status_code == 404

    one = (await biz.owner.client.get(biz.inbox, params={"limit": 1})).json()
    assert [i["id"] for i in one["items"]] == [second] and one["next_before"]
    rest = (await biz.owner.client.get(biz.inbox, params={
        "limit": 1, "before": one["next_before"]})).json()  # fmt: skip
    assert [i["id"] for i in rest["items"]] == [first] and rest["next_before"] is None


async def test_every_role_can_work_the_inbox_and_outsiders_cannot(harness: AppHarness) -> None:
    biz = await _business(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    outsider = await signup(harness)
    _, _, conv_id = await _visitor(harness, biz)
    for acc in (biz.owner, admin, member):
        assert (await acc.client.get(biz.inbox)).status_code == 200
        assert (await acc.client.post(f"{biz.inbox}/{conv_id}/take-over")).status_code == 204
    assert (await outsider.client.get(biz.inbox)).status_code == 404
    assert (await outsider.client.post(f"{biz.inbox}/{conv_id}/resolve")).status_code == 404
    anon = harness.new_client()
    assert (await anon.get(biz.inbox)).status_code == 401
