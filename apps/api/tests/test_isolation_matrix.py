"""Cross-tenant isolation matrix: every business-scoped route, every method.

Routes are discovered from the app, so a new `/api/businesses/{business_id}/...` endpoint is
covered automatically. A user who is Owner of business A must get 404 for every route
when addressing business B, and must not change anything in B.
"""

import uuid

import pytest
from httpx import AsyncClient

from agentree.core.config import Settings
from agentree.main import create_app
from tests.conftest import AppHarness
from tests.helpers import create_business, invite_and_join, signup

PLACEHOLDER_BODIES = {
    "POST": {"email": "probe@example.com", "role": "member"},
    "PATCH": {"role": "member"},
    "PUT": {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "sk-probe-0000-1111",
        "verify": False,
    },
}


def _business_routes() -> list[tuple[str, str]]:
    # Discover from the OpenAPI schema: it lists every mounted route, including routers
    # included lazily by FastAPI.
    settings = Settings(database_url="postgresql+asyncpg://u:p@localhost/db")
    paths = create_app(settings).openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, ops in paths.items()
        if "{business_id}" in path
        for method in ops
    )


BUSINESS_ROUTES = _business_routes()


def test_matrix_covers_known_routes() -> None:
    assert len(BUSINESS_ROUTES) >= 7, BUSINESS_ROUTES
    assert ("PUT", "/api/businesses/{business_id}/public-profile") in BUSINESS_ROUTES


async def _snapshot(client: AsyncClient, business_id: str) -> tuple[object, ...]:
    base = f"/api/businesses/{business_id}"
    return (
        (await client.get(base)).json(),
        (await client.get(f"{base}/members")).json(),
        (await client.get(f"{base}/invitations")).json(),
        (await client.get(f"{base}/ai-providers")).json(),
        (await client.get(f"{base}/knowledge")).json(),
        (await client.get(f"{base}/public-profile")).json(),
        (await client.get(f"{base}/audit-events")).json(),
        (await client.get(f"{base}/leads")).json(),
        (await client.get(f"{base}/inbox")).json(),
    )


@pytest.mark.parametrize(("method", "path"), BUSINESS_ROUTES)
async def test_owner_of_a_cannot_touch_b(harness: AppHarness, method: str, path: str) -> None:
    alice = await signup(harness)
    bob = await signup(harness)
    await create_business(alice, "A")
    b = await create_business(bob, "B")
    bob_member = await invite_and_join(harness, bob, b["id"], "member")
    r = await bob.client.put(
        f"/api/businesses/{b['id']}/ai-providers/primary", json=PLACEHOLDER_BODIES["PUT"]
    )
    assert r.status_code == 200, r.text
    entry = await bob.client.post(
        f"/api/businesses/{b['id']}/knowledge", json={"title": "B only", "body": "B knowledge"}
    )
    convo = await bob.client.post(
        f"/api/businesses/{b['id']}/agents/sales/console", json={"message": "hello"}
    )
    assert convo.status_code == 200, convo.text
    r = await bob.client.put(
        f"/api/businesses/{b['id']}/public-profile",
        json={"enabled": True, "bio": "B page", "widget_origins": ["https://b.example.com"]},
    )
    assert r.status_code == 200, r.text
    pending = await bob.client.post(
        f"/api/businesses/{b['id']}/invitations", json={"email": "p@example.com"}
    )
    # A real lead in B: a visitor of B's public page confirms their details.
    visitor = harness.new_client()
    pub = f"/api/public/{b['slug']}"
    guest = {"X-Agentree-Guest": (await visitor.post(f"{pub}/sessions")).json()["token"]}
    chat = await visitor.post(f"{pub}/chat", json={"message": "hi"}, headers=guest)
    assert chat.status_code == 200, chat.text
    lead = await visitor.post(f"{pub}/leads", headers=guest, json={
        "conversation_id": chat.json()["conversation_id"], "email": "v@example.com",
        "consent": True, "idempotency_key": "matrix-lead-1"})  # fmt: skip
    assert lead.status_code == 200, lead.text
    lead_id = (await bob.client.get(f"/api/businesses/{b['id']}/leads")).json()["leads"][0]["id"]
    task_id = (
        await bob.client.get(f"/api/businesses/{b['id']}/leads/{lead_id}/follow-ups")
    ).json()[0]["id"]
    before = await _snapshot(bob.client, b["id"])
    url = path.format(
        business_id=b["id"],
        user_id=bob_member.id,  # a real user in B
        invitation_id=pending.json()["id"],  # a real invitation in B
        slot="primary",  # B has a stored primary key
        entry_id=entry.json()["id"],  # a real knowledge entry in B
        # A real conversation in B: the visitor's for the inbox, the console one elsewhere.
        conversation_id=chat.json()["conversation_id"]
        if "/inbox/" in path
        else convo.json()["conversation_id"],
        lead_id=lead_id,  # a real lead in B
        task_id=task_id,  # a real follow-up task in B
    )
    r = await alice.client.request(method, url, json=PLACEHOLDER_BODIES.get(method))
    assert r.status_code == 404, (method, url, r.status_code, r.text)

    after = await _snapshot(bob.client, b["id"])
    assert after[0] == before[0] and after[1] == before[1]
    assert after[3] == before[3] and after[4] == before[4] and after[5] == before[5]
    assert after[6] == before[6] and after[7] == before[7] and after[8] == before[8]


@pytest.mark.parametrize(("method", "path"), BUSINESS_ROUTES)
async def test_unknown_business_is_404_not_403(harness: AppHarness, method: str, path: str) -> None:
    alice = await signup(harness)
    url = path.format(
        business_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        invitation_id=uuid.uuid4(),
        slot="primary",
        entry_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
    )
    r = await alice.client.request(method, url, json=PLACEHOLDER_BODIES.get(method))
    assert r.status_code == 404


@pytest.mark.parametrize(("method", "path"), BUSINESS_ROUTES)
async def test_anonymous_is_rejected(harness: AppHarness, method: str, path: str) -> None:
    c = harness.new_client()
    url = path.format(
        business_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        invitation_id=uuid.uuid4(),
        slot="primary",
        entry_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        lead_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
    )
    r = await c.request(method, url, json=PLACEHOLDER_BODIES.get(method))
    assert r.status_code == 401
