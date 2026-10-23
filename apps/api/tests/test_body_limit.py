"""Request body size limit (Task 22 security review): oversized bodies are refused while they
stream in, before any endpoint spools them to disk."""

from collections.abc import AsyncIterator

from tests.conftest import AppHarness
from tests.helpers import create_business, signup

MIB = 1024 * 1024


async def _chunks(total: int, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    for _ in range(total // size):
        yield b"x" * size


async def test_a_declared_oversized_body_is_refused_at_once(harness: AppHarness) -> None:
    c = harness.new_client()
    r = await c.post(
        "/api/auth/login",
        content=b"{}",
        headers={"content-length": str(2 * MIB), "content-type": "application/json"},
    )
    assert r.status_code == 413 and r.json() == {"detail": "request_too_large"}


async def test_a_chunked_body_stops_at_the_limit(harness: AppHarness) -> None:
    c = harness.new_client()
    r = await c.post("/api/auth/login", content=_chunks(2 * MIB),
                     headers={"content-type": "application/json"})  # fmt: skip
    assert r.status_code == 413


async def test_uploads_get_their_own_larger_limit(harness: AppHarness) -> None:
    owner = await signup(harness)
    business = await create_business(owner, "Big Files")
    url = f"/api/businesses/{business['id']}/knowledge-files"
    # 2 MiB is fine for an upload (refused later only because it is not a real document)...
    r = await owner.client.post(url, files={"file": ("notes.txt", b"hello " * (2 * MIB // 6))})
    assert r.status_code != 413
    # ...but not past the 10 MB file limit plus multipart overhead.
    r = await owner.client.post(url, files={"file": ("big.txt", b"a" * (11 * MIB))})
    assert r.status_code == 413
