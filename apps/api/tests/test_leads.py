"""Leads: model suggestion -> visitor confirmation -> gateway-created lead -> dashboard follow-up."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agentree.actions import service as gateway
from agentree.agents.prompts import split_lead_marker
from agentree.llm.base import ProviderName
from agentree.llm.fake import FakeProvider
from tests.conftest import AppHarness
from tests.helpers import Account, create_business, invite_and_join, signup

KEY = "sk-leads-primary-key-dddd4444"  # gitleaks:allow (fake test key)
MARKER = '<<LEAD {"name": "Sara", "email": "sara@example.com", "phone": "", "need": "A desk"}>>'


class Biz:
    def __init__(self, owner: Account, business: dict[str, Any]) -> None:
        self.owner, self.id, self.slug = owner, business["id"], business["slug"]
        self.base = f"/api/businesses/{self.id}"
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


async def _conversation(
    h: AppHarness, biz: Biz, c: AsyncClient, auth: dict[str, str],
    message: str = "I'm Sara, sara@example.com. I want a standing desk.",
    reply: str = f"Thanks Sara! Our team will reach out.\n{MARKER}",
) -> dict[str, Any]:  # fmt: skip
    _fake(h).replies.append(reply)
    r = await c.post(f"{biz.pub}/chat", json={"message": message}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def _lead_body(conversation_id: str, **over: Any) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id, "name": "Sara", "email": "Sara@Example.com",
        "phone": "", "need": "A standing desk", "consent": True,
        "idempotency_key": uuid.uuid4().hex,
    } | over  # fmt: skip


async def _leads(acc: Account, biz: Biz) -> list[dict[str, Any]]:
    r = await acc.client.get(f"{biz.base}/leads")
    assert r.status_code == 200, r.text
    return r.json()["leads"]  # type: ignore[no-any-return]


# --- suggestion from the conversation -----------------------------------------------------


async def test_marker_becomes_a_suggestion_and_is_never_shown_or_stored(
    harness: AppHarness,
) -> None:
    biz = await _business(harness)
    c = harness.new_client()
    auth = await _guest(c, biz)
    out = await _conversation(harness, biz, c, auth)
    assert out["reply"] == "Thanks Sara! Our team will reach out."
    assert out["lead_suggestion"] == {
        "name": "Sara", "email": "sara@example.com", "phone": "", "need": "A desk",
    }  # fmt: skip
    r = await c.get(f"{biz.pub}/conversations/{out['conversation_id']}/messages", headers=auth)
    assert "<<LEAD" not in r.text
    # The public prompt explains the marker; the visitor's own text decides what is kept.
    system = _fake(harness).calls[-1][1].messages[0].content
    assert "<<LEAD" in system


def test_suggestion_keeps_only_contact_details_the_visitor_wrote() -> None:
    reply = (
        'Sure.\n<<LEAD {"name": "X", "email": "evil@attacker.test", "phone": "+1 555 0100 999"}>>'
    )
    clean, suggestion = split_lead_marker(reply, ["call me at +1 (555) 0100-999"])
    assert clean == "Sure."
    assert suggestion is not None and suggestion.email == "" and suggestion.phone
    _, none = split_lead_marker(reply, ["no contact details here"])
    assert none is None
    clean, bad = split_lead_marker("Hi <<LEAD not json>> there", ["a@b.co"])
    assert "<<LEAD" not in clean and clean.startswith("Hi")
    assert bad is None


async def test_no_marker_means_no_suggestion(harness: AppHarness) -> None:
    biz = await _business(harness)
    c = harness.new_client()
    out = await _conversation(harness, biz, c, await _guest(c, biz), reply="Our desks cost $499.")
    assert out["lead_suggestion"] is None


# --- visitor confirms -> lead --------------------------------------------------------------


async def test_confirmed_details_create_one_lead_and_alert_owners_and_admins(
    harness: AppHarness,
) -> None:
    biz = await _business(harness)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    c = harness.new_client()
    auth = await _guest(c, biz)
    convo = await _conversation(harness, biz, c, auth)
    body = _lead_body(convo["conversation_id"])
    sent_before = len(harness.mailer.sent)
    for _ in range(3):  # client retries with the same idempotency key
        r = await c.post(f"{biz.pub}/leads", json=body, headers=auth)
        assert r.status_code == 200, r.text
        assert r.json() == {"received": True}

    leads = await _leads(biz.owner, biz)
    assert len(leads) == 1
    lead = leads[0]
    assert lead["email"] == "sara@example.com" and lead["name"] == "Sara"
    assert lead["status"] == "new" and lead["channel"] == "public"
    assert lead["source_agent"] == "sales" and lead["conversation_id"] == convo["conversation_id"]

    alerts = harness.mailer.sent[sent_before:]
    assert sorted(m.to for m in alerts) == sorted([biz.owner.email, admin.email])
    assert member.email not in [m.to for m in alerts]
    assert all(m.html and f"/leads/{lead['id']}" in m.body for m in alerts)

    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    created = [e for e in events if e["action"] == "lead.created"]
    assert len(created) == 1 and created[0]["actor"] is None
    assert created[0]["details"] == {"channel": "public", "agent": "sales"}
    assert "sara@example.com" not in str(created)


async def test_resubmission_updates_the_same_lead_without_a_new_alert(harness: AppHarness) -> None:
    biz = await _business(harness)
    c = harness.new_client()
    auth = await _guest(c, biz)
    convo = await _conversation(harness, biz, c, auth)
    assert (await c.post(f"{biz.pub}/leads", json=_lead_body(convo["conversation_id"]),
                         headers=auth)).status_code == 200  # fmt: skip
    sent = len(harness.mailer.sent)
    r = await c.post(f"{biz.pub}/leads", headers=auth, json=_lead_body(
        convo["conversation_id"], phone="+1 (555) 010-0999", need="Two desks"))  # fmt: skip
    assert r.status_code == 200, r.text
    leads = await _leads(biz.owner, biz)
    assert len(leads) == 1 and leads[0]["need"] == "Two desks"
    assert leads[0]["phone"] == "+1 (555) 010-0999"
    assert len(harness.mailer.sent) == sent


async def test_reused_key_with_different_details_is_refused(harness: AppHarness) -> None:
    biz = await _business(harness)
    c = harness.new_client()
    auth = await _guest(c, biz)
    convo = await _conversation(harness, biz, c, auth)
    body = _lead_body(convo["conversation_id"])
    assert (await c.post(f"{biz.pub}/leads", json=body, headers=auth)).status_code == 200
    r = await c.post(f"{biz.pub}/leads", json=body | {"need": "Changed"}, headers=auth)
    assert r.status_code == 409 and r.json()["detail"] == "idempotency_conflict"


@pytest.mark.parametrize(
    ("over", "detail"),
    [
        ({"consent": False}, None),
        ({"email": "", "phone": ""}, "invalid_contact"),
        ({"email": "not-an-email"}, "invalid_email"),
        ({"email": "", "phone": "12"}, "invalid_phone"),
        ({"idempotency_key": "bad key!"}, None),
        ({"extra": 1}, None),
    ],
)
async def test_invalid_submissions_are_rejected(
    harness: AppHarness, over: dict[str, Any], detail: str | None
) -> None:
    biz = await _business(harness)
    c = harness.new_client()
    auth = await _guest(c, biz)
    convo = await _conversation(harness, biz, c, auth)
    body = _lead_body(convo["conversation_id"]) | over
    if over == {"consent": False}:
        body.pop("consent")
        r0 = await c.post(f"{biz.pub}/leads", json=body, headers=auth)
        assert r0.status_code == 422
        body["consent"] = False
    r = await c.post(f"{biz.pub}/leads", json=body, headers=auth)
    assert r.status_code == 422, r.text
    if detail:
        assert r.json()["detail"] == detail
    assert await _leads(biz.owner, biz) == []


async def test_guest_can_only_attach_a_lead_to_their_own_conversation(
    harness: AppHarness,
) -> None:
    biz = await _business(harness)
    c1, c2 = harness.new_client(), harness.new_client()
    auth1, auth2 = await _guest(c1, biz), await _guest(c2, biz)
    convo = await _conversation(harness, biz, c1, auth1)
    r = await c2.post(f"{biz.pub}/leads", json=_lead_body(convo["conversation_id"]), headers=auth2)
    assert r.status_code == 404
    r = await c1.post(f"{biz.pub}/leads", json=_lead_body(str(uuid.uuid4())), headers=auth1)
    assert r.status_code == 404
    r = await c1.post(f"{biz.pub}/leads", json=_lead_body(convo["conversation_id"]))
    assert r.status_code == 401
    other = await _business(harness)  # another business cannot see this conversation
    auth3 = await _guest(c1, other)
    r = await c1.post(f"{other.pub}/leads", json=_lead_body(convo["conversation_id"]),
                      headers=auth3)  # fmt: skip
    assert r.status_code == 404
    assert await _leads(biz.owner, biz) == [] and await _leads(other.owner, other) == []


# --- gateway -------------------------------------------------------------------------------


def test_gateway_refuses_agents_without_the_permission() -> None:
    gateway.authorize("sales", gateway.Action.CREATE_LEAD)
    for agent in ("technical_support", "data_analyst", "executive", ""):
        with pytest.raises(gateway.ActionDeniedError):
            gateway.authorize(agent, gateway.Action.CREATE_LEAD)


# --- dashboard follow-up -------------------------------------------------------------------


async def _one_lead(h: AppHarness) -> tuple[Biz, dict[str, Any]]:
    biz = await _business(h)
    c = h.new_client()
    auth = await _guest(c, biz)
    convo = await _conversation(h, biz, c, auth)
    assert (await c.post(f"{biz.pub}/leads", json=_lead_body(convo["conversation_id"]),
                         headers=auth)).status_code == 200  # fmt: skip
    return biz, (await _leads(biz.owner, biz))[0]


async def test_members_follow_up_admins_delete(harness: AppHarness) -> None:
    biz, lead = await _one_lead(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    url = f"{biz.base}/leads/{lead['id']}"

    detail = (await member.client.get(url)).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert "<<LEAD" not in str(detail["messages"])

    r = await member.client.patch(url, json={"status": "contacted", "notes": "Called, wants 2."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "contacted" and r.json()["notes"] == "Called, wants 2."
    assert (await member.client.patch(url, json={"status": "bogus"})).status_code == 422
    assert (await member.client.delete(url)).status_code == 403

    filtered = await biz.owner.client.get(f"{biz.base}/leads", params={"status": "contacted"})
    assert [x["id"] for x in filtered.json()["leads"]] == [lead["id"]]
    empty = await biz.owner.client.get(f"{biz.base}/leads", params={"status": "won"})
    assert empty.json()["leads"] == []

    assert (await biz.owner.client.delete(url)).status_code == 204
    assert (await biz.owner.client.get(url)).status_code == 404
    events = (await biz.owner.client.get(f"{biz.base}/audit-events")).json()["events"]
    assert events[0]["action"] == "lead.deleted"
    # Status and notes changed in one request: same transaction, order within it not defined.
    # Moving past "new" also closes the agent's first-contact follow-up (test_follow_ups.py).
    same_request = {e["action"]: e for e in events[1:4]}
    assert set(same_request) == {"lead.status_changed", "lead.notes_updated", "follow_up.updated"}
    assert same_request["lead.status_changed"]["details"] == {
        "from_status": "new", "to_status": "contacted",
    }  # fmt: skip


async def test_lead_outlives_its_conversation(
    harness: AppHarness, migrator_engine: AsyncEngine
) -> None:
    biz, lead = await _one_lead(harness)
    async with migrator_engine.begin() as conn:  # what the retention purge does
        await conn.execute(text("DELETE FROM conversations WHERE id = :id"),
                           {"id": lead["conversation_id"]})  # fmt: skip
    detail = (await biz.owner.client.get(f"{biz.base}/leads/{lead['id']}")).json()
    assert detail["conversation_id"] is None and detail["messages"] == []
    assert detail["email"] == "sara@example.com"


async def test_pagination(harness: AppHarness) -> None:
    biz = await _business(harness)
    for _ in range(3):
        c = harness.new_client()
        auth = await _guest(c, biz)
        convo = await _conversation(harness, biz, c, auth)
        assert (await c.post(f"{biz.pub}/leads", json=_lead_body(convo["conversation_id"]),
                             headers=auth)).status_code == 200  # fmt: skip
    first = (await biz.owner.client.get(f"{biz.base}/leads", params={"limit": 2})).json()
    assert len(first["leads"]) == 2 and first["next_before"]
    rest = (await biz.owner.client.get(f"{biz.base}/leads",
                                       params={"limit": 2, "before": first["next_before"]})).json()  # fmt: skip
    assert len(rest["leads"]) == 1 and rest["next_before"] is None
