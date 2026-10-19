"""Knowledge base API and retrieval."""

from uuid import UUID

from agentree.knowledge import service
from agentree.tenancy.context import TenantContext, TenantSource
from tests.conftest import AppHarness
from tests.helpers import create_business, invite_and_join, signup


async def test_draft_publish_edit_cycle(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    base = f"/api/businesses/{biz['id']}/knowledge"
    r = await owner.client.post(base, json={"title": "Pricing", "body": "Basic plan is $49/month."})
    assert r.status_code == 201 and r.json()["status"] == "draft"
    eid = r.json()["id"]
    r = await owner.client.post(f"{base}/{eid}/publish")
    assert r.json()["status"] == "published" and r.json()["published_at"]
    r = await owner.client.patch(f"{base}/{eid}", json={"body": "Basic plan is $59/month."})
    assert r.json()["status"] == "draft"  # edits need re-publishing
    assert len((await owner.client.get(base)).json()) == 1
    assert (await owner.client.delete(f"{base}/{eid}")).status_code == 204
    assert (await owner.client.get(f"{base}/{eid}")).status_code == 404


async def test_member_drafts_but_cannot_publish_or_delete(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    member = await invite_and_join(harness, owner, biz["id"], "member")
    base = f"/api/businesses/{biz['id']}/knowledge"
    r = await member.client.post(base, json={"title": "FAQ", "body": "We ship worldwide."})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert (await member.client.post(f"{base}/{eid}/publish")).status_code == 403
    assert (await member.client.delete(f"{base}/{eid}")).status_code == 403
    assert (await owner.client.post(f"{base}/{eid}/publish")).status_code == 200


async def _publish(owner_client, base: str, title: str, body: str) -> str:  # type: ignore[no-untyped-def]
    r = await owner_client.post(base, json={"title": title, "body": body})
    eid = r.json()["id"]
    await owner_client.post(f"{base}/{eid}/publish")
    return str(eid)


async def test_retrieval_returns_only_published_entries_of_this_business(
    harness: AppHarness,
) -> None:
    alice = await signup(harness)
    bob = await signup(harness)
    a = await create_business(alice, "A")
    b = await create_business(bob, "B")
    base_a, base_b = f"/api/businesses/{a['id']}/knowledge", f"/api/businesses/{b['id']}/knowledge"
    await _publish(alice.client, base_a, "Warranty", "Two year warranty on all chairs.")
    await alice.client.post(
        base_a, json={"title": "Secret draft", "body": "Unreleased chair launch."}
    )
    await _publish(bob.client, base_b, "Bob warranty", "Bob offers no warranty.")
    factory = harness.app.state.session_factory
    got = await service.retrieve(
        factory, TenantContext(UUID(a["id"]), TenantSource.MEMBERSHIP), "warranty"
    )
    assert [e.title for e in got] == ["Warranty"]


async def test_large_knowledge_base_uses_full_text_ranking(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    base = f"/api/businesses/{biz['id']}/knowledge"
    for i in range(service.SMALL_KB_ENTRIES + 2):
        await _publish(owner.client, base, f"Topic {i}", f"General information number {i}.")
    await _publish(
        owner.client, base, "Refund policy", "Refunds are accepted within 30 days of purchase."
    )
    factory = harness.app.state.session_factory
    ctx = TenantContext(UUID(biz["id"]), TenantSource.MEMBERSHIP)
    got = await service.retrieve(factory, ctx, "can I get a refund?")
    assert got and got[0].title == "Refund policy"
    assert all("refund" in (e.title + e.body).lower() for e in got)
    assert await service.retrieve(factory, ctx, "hi") == []  # stop words only: no error, no match
    assert (
        await service.retrieve(factory, ctx, "it's & | ! (") == []
    )  # tsquery syntax is not injectable


async def test_body_size_is_limited(harness: AppHarness) -> None:
    owner = await signup(harness)
    biz = await create_business(owner)
    r = await owner.client.post(
        f"/api/businesses/{biz['id']}/knowledge",
        json={"title": "Big", "body": "x" * (service.MAX_BODY_CHARS + 1)},
    )
    assert r.status_code == 422
