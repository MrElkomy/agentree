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


async def _snapshot(client: AsyncClient, business_id: str) -> tuple[object, object, object]:
    base = f"/api/businesses/{business_id}"
    return (
        (await client.get(base)).json(),
        (await client.get(f"{base}/members")).json(),
        (await client.get(f"{base}/invitations")).json(),
    )


@pytest.mark.parametrize(("method", "path"), BUSINESS_ROUTES)
async def test_owner_of_a_cannot_touch_b(harness: AppHarness, method: str, path: str) -> None:
    alice = await signup(harness)
    bob = await signup(harness)
    await create_business(alice, "A")
    b = await create_business(bob, "B")
    bob_member = await invite_and_join(harness, bob, b["id"], "member")
    before = await _snapshot(bob.client, b["id"])

    pending = await bob.client.post(
        f"/api/businesses/{b['id']}/invitations", json={"email": "p@example.com"}
    )
    url = path.format(
        business_id=b["id"],
        user_id=bob_member.id,  # a real user in B
        invitation_id=pending.json()["id"],  # a real invitation in B
    )
    r = await alice.client.request(method, url, json=PLACEHOLDER_BODIES.get(method))
    assert r.status_code == 404, (method, url, r.status_code, r.text)

    after = await _snapshot(bob.client, b["id"])
    assert after[0] == before[0] and after[1] == before[1]


@pytest.mark.parametrize(("method", "path"), BUSINESS_ROUTES)
async def test_unknown_business_is_404_not_403(harness: AppHarness, method: str, path: str) -> None:
    alice = await signup(harness)
    url = path.format(business_id=uuid.uuid4(), user_id=uuid.uuid4(), invitation_id=uuid.uuid4())
    r = await alice.client.request(method, url, json=PLACEHOLDER_BODIES.get(method))
    assert r.status_code == 404


@pytest.mark.parametrize(("method", "path"), BUSINESS_ROUTES)
async def test_anonymous_is_rejected(harness: AppHarness, method: str, path: str) -> None:
    c = harness.new_client()
    url = path.format(business_id=uuid.uuid4(), user_id=uuid.uuid4(), invitation_id=uuid.uuid4())
    r = await c.request(method, url, json=PLACEHOLDER_BODIES.get(method))
    assert r.status_code == 401
