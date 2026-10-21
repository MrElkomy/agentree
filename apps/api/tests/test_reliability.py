"""AI reliability: per-key circuit breaker, return to primary, streamed replies, monitoring."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from agentree.core import metrics
from agentree.llm.base import ErrorKind, ProviderName
from agentree.llm.fake import FakeProvider, Interrupted
from agentree.main import create_app
from agentree.providers import service as providers
from agentree.tenancy.context import TenantContext, TenantSource
from tests.conftest import AppHarness, DbUrls, FakeMailer, _admin_execute, _client, _returning
from tests.helpers import Account, create_business, signup

PRIMARY_KEY = "sk-primary-key-rrrr1111"  # gitleaks:allow (fake test key)
BACKUP_KEY = "sk-backup-key-rrrr2222"  # gitleaks:allow (fake test key)
LEAD = '<<LEAD {"name": "Ana", "email": "ana@example.com", "phone": "", "need": "Desk"}>>'


class Biz:
    def __init__(self, owner: Account, business: dict[str, Any]) -> None:
        self.owner, self.id, self.slug = owner, business["id"], business["slug"]
        self.base = f"/api/businesses/{self.id}"
        self.console = f"{self.base}/agents/sales/console"
        self.pub = f"/api/public/{self.slug}"


async def _business(h: AppHarness, *, backup: bool = False, public: bool = False) -> Biz:
    owner = await signup(h)
    biz = Biz(owner, await create_business(owner, "Maple Beds"))
    r = await owner.client.put(f"{biz.base}/ai-providers/primary", json={
        "provider": "openai", "model": "gpt-4o-mini", "api_key": PRIMARY_KEY, "verify": False})  # fmt: skip
    assert r.status_code == 200, r.text
    if backup:
        r = await owner.client.put(f"{biz.base}/ai-providers/backup", json={
            "provider": "anthropic", "model": "claude-haiku", "api_key": BACKUP_KEY,
            "verify": False})  # fmt: skip
        assert r.status_code == 200, r.text
    if public:
        r = await owner.client.put(f"{biz.base}/public-profile", json={"enabled": True})
        assert r.status_code == 200, r.text
    return biz


def _primary(h: AppHarness) -> FakeProvider:
    return h.llm[ProviderName.OPENAI]


def _backup(h: AppHarness) -> FakeProvider:
    return h.llm[ProviderName.ANTHROPIC]


async def _ask(biz: Biz, message: str = "Do you sell beds?") -> Any:
    return await biz.owner.client.post(biz.console, json={"message": message})


async def _health(biz: Biz) -> dict[str, dict[str, Any]]:
    r = await biz.owner.client.get(f"{biz.base}/ai-providers")
    assert r.status_code == 200, r.text
    return {c["slot"]: c for c in r.json()}


async def _end_cooldown(db_urls: DbUrls, biz: Biz, slot: str = "primary") -> None:
    await _admin_execute(db_urls.admin, (
        "UPDATE provider_credentials SET breaker_open_until = now() - interval '1 second' "
        f"WHERE business_id = '{uuid.UUID(biz.id)}' AND slot = '{slot}'"))  # fmt: skip


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


# --- circuit breaker --------------------------------------------------------------------------


async def test_breaker_opens_after_repeated_outages_and_stops_calling_the_key(
    harness: AppHarness, db_urls: DbUrls
) -> None:
    biz = await _business(harness)
    for _ in range(providers.FAILURE_THRESHOLD):
        _primary(harness).replies.append(ErrorKind.UNAVAILABLE)
        r = await _ask(biz)
        assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_unavailable"
    health = (await _health(biz))["primary"]
    assert health["health"] == "down" and health["breaker_open_until"]
    assert health["last_error_kind"] == "unavailable"

    calls = len(_primary(harness).calls)
    r = await _ask(biz)
    assert r.status_code == 503
    assert r.json()["detail"]["errors"] == ["circuit_open"]
    assert len(_primary(harness).calls) == calls  # the open key was not called

    # Cooldown over: the next turn probes the key; success closes the breaker.
    await _end_cooldown(db_urls, biz)
    assert (await _health(biz))["primary"]["health"] == "recovering"
    _primary(harness).replies.append("We do!")
    r = await _ask(biz)
    assert r.status_code == 200 and r.json()["reply"] == "We do!"
    health = (await _health(biz))["primary"]
    assert health["health"] == "healthy" and health["breaker_open_until"] is None


async def test_backup_answers_while_primary_is_down_then_traffic_returns_to_primary(
    harness: AppHarness, db_urls: DbUrls
) -> None:
    biz = await _business(harness, backup=True)
    for i in range(providers.FAILURE_THRESHOLD):
        _primary(harness).replies.append(ErrorKind.RATE_LIMIT)
        _backup(harness).replies.append(f"backup {i}")
        r = await _ask(biz)
        assert r.json()["slot"] == "backup" and r.json()["fallback_used"] is True

    primary_calls = len(_primary(harness).calls)
    _backup(harness).replies.append("backup while open")
    r = await _ask(biz)
    assert r.json() == {**r.json(), "slot": "backup", "reply": "backup while open"}
    assert len(_primary(harness).calls) == primary_calls  # skipped, no wasted call
    health = await _health(biz)
    assert health["primary"]["health"] == "down" and health["backup"]["health"] == "healthy"

    await _end_cooldown(db_urls, biz)
    _primary(harness).replies.append("primary is back")
    r = await _ask(biz)
    assert r.json() == {**r.json(), "slot": "primary", "fallback_used": False,
                        "reply": "primary is back"}  # fmt: skip
    assert (await _health(biz))["primary"]["health"] == "healthy"


async def test_failed_probe_reopens_with_a_longer_cooldown(
    harness: AppHarness, db_urls: DbUrls
) -> None:
    biz = await _business(harness)
    for _ in range(providers.FAILURE_THRESHOLD):
        _primary(harness).replies.append(ErrorKind.TRANSIENT)
        await _ask(biz)
    first = (await _health(biz))["primary"]
    await _end_cooldown(db_urls, biz)
    _primary(harness).replies.append(ErrorKind.TRANSIENT)
    assert (await _ask(biz)).status_code == 503
    second = (await _health(biz))["primary"]
    assert second["health"] == "down"
    first_wait = _seconds(first["breaker_open_until"], first["last_failure_at"])
    second_wait = _seconds(second["breaker_open_until"], second["last_failure_at"])
    assert second_wait > first_wait


def _seconds(until: str, since: str) -> float:
    return (datetime.fromisoformat(until) - datetime.fromisoformat(since)).total_seconds()


async def test_auth_error_opens_at_once_and_a_bad_request_never_trips(
    harness: AppHarness,
) -> None:
    biz = await _business(harness)
    for _ in range(providers.FAILURE_THRESHOLD + 1):
        _primary(harness).replies.append(ErrorKind.BAD_REQUEST)
        assert (await _ask(biz)).status_code == 503
    health = (await _health(biz))["primary"]
    assert health["health"] == "degraded" and health["breaker_open_until"] is None

    _primary(harness).replies.append(ErrorKind.AUTH)
    await _ask(biz)
    assert (await _health(biz))["primary"]["health"] == "down"


async def test_only_one_probe_at_a_time(harness: AppHarness, db_urls: DbUrls) -> None:
    biz = await _business(harness)
    for _ in range(providers.FAILURE_THRESHOLD):
        _primary(harness).replies.append(ErrorKind.UNAVAILABLE)
        await _ask(biz)
    await _end_cooldown(db_urls, biz)
    factory = harness.app.state.session_factory
    ctx = TenantContext(uuid.UUID(biz.id), TenantSource.JOB)
    assert await providers.admit(factory, ctx, providers.Slot.PRIMARY) == providers.Admission.PROBE
    assert await providers.admit(factory, ctx, providers.Slot.PRIMARY) == providers.Admission.OPEN


async def test_a_successful_manual_test_closes_the_breaker(harness: AppHarness) -> None:
    biz = await _business(harness)
    _primary(harness).replies.append(ErrorKind.QUOTA)  # key problem: opens at once
    await _ask(biz)
    assert (await _health(biz))["primary"]["health"] == "down"
    _primary(harness).replies.append("OK")
    r = await biz.owner.client.post(f"{biz.base}/ai-providers/primary/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (await _health(biz))["primary"]["health"] == "healthy"


async def test_replacing_the_key_starts_with_a_closed_breaker(harness: AppHarness) -> None:
    biz = await _business(harness)
    _primary(harness).replies.append(ErrorKind.AUTH)
    await _ask(biz)
    assert (await _health(biz))["primary"]["health"] == "down"
    r = await biz.owner.client.put(f"{biz.base}/ai-providers/primary", json={
        "provider": "openai", "model": "gpt-4o-mini", "api_key": PRIMARY_KEY + "x",
        "verify": False})  # fmt: skip
    assert r.status_code == 200
    assert (await _health(biz))["primary"]["health"] == "healthy"


# --- streaming ------------------------------------------------------------------------------


async def test_console_stream_sends_deltas_then_the_final_reply(harness: AppHarness) -> None:
    biz = await _business(harness)
    _primary(harness).replies.append("We sell queen and king beds.")
    r = await biz.owner.client.post(f"{biz.console}/stream", json={"message": "Beds?"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in r.headers["cache-control"]
    events = _events(r.text)
    deltas = [d["text"] for e, d in events if e == "delta"]
    assert len(deltas) > 1 and "".join(deltas) == "We sell queen and king beds."
    name, done = events[-1]
    assert name == "done" and done["reply"] == "We sell queen and king beds."
    assert done["slot"] == "primary"
    messages = (await biz.owner.client.get(
        f"{biz.base}/conversations/{done['conversation_id']}/messages")).json()  # fmt: skip
    assert [m["role"] for m in messages] == ["user", "assistant"]


async def test_public_stream_never_shows_markers(harness: AppHarness) -> None:
    biz = await _business(harness, public=True)
    c = harness.new_client()
    token = (await c.post(f"{biz.pub}/sessions")).json()["token"]
    _primary(harness).replies.append(f"Thanks Ana, the team will email you.\n{LEAD}\n<<HANDOFF>>")
    r = await c.post(f"{biz.pub}/chat/stream", headers={"X-Agentree-Guest": token},
                     json={"message": "I'm Ana, ana@example.com, can a person call me?"})  # fmt: skip
    assert r.status_code == 200, r.text
    events = _events(r.text)
    streamed = "".join(d["text"] for e, d in events if e == "delta")
    assert "<<" not in streamed and "LEAD" not in streamed and "HANDOFF" not in streamed
    name, done = events[-1]
    assert name == "done"
    assert done["reply"] == "Thanks Ana, the team will email you."
    assert done["lead_suggestion"]["email"] == "ana@example.com"
    assert done["status"] == "needs_human"
    # The handoff alert runs after the stream, like the JSON endpoint.
    assert any(f"/inbox/{done['conversation_id']}" in m.body for m in harness.mailer.sent)


async def test_mid_stream_outage_restarts_on_the_backup(harness: AppHarness) -> None:
    biz = await _business(harness, backup=True)
    _primary(harness).replies.append(Interrupted("Our beds are", ErrorKind.UNAVAILABLE))
    _backup(harness).replies.append("Beds start at $400.")
    r = await biz.owner.client.post(f"{biz.console}/stream", json={"message": "Price?"})
    events = _events(r.text)
    names = [e for e, _ in events]
    restart = names.index("restart")
    before = "".join(d["text"] for e, d in events[:restart] if e == "delta")
    after = "".join(d["text"] for e, d in events[restart:] if e == "delta")
    assert before == "Our beds are" and after == "Beds start at $400."
    done = events[-1][1]
    assert done["reply"] == "Beds start at $400." and done["slot"] == "backup"
    messages = (await biz.owner.client.get(
        f"{biz.base}/conversations/{done['conversation_id']}/messages")).json()  # fmt: skip
    assert [m["content"] for m in messages] == ["Price?", "Beds start at $400."]


async def test_mid_stream_outage_without_backup_ends_with_an_error_and_stores_nothing(
    harness: AppHarness,
) -> None:
    biz = await _business(harness, public=True)
    c = harness.new_client()
    auth = {"X-Agentree-Guest": (await c.post(f"{biz.pub}/sessions")).json()["token"]}
    _primary(harness).replies.append("Hello")  # first turn creates the conversation
    first = await c.post(f"{biz.pub}/chat", json={"message": "Hi"}, headers=auth)
    conv_id = first.json()["conversation_id"]

    _primary(harness).replies.append(Interrupted("Half a rep", ErrorKind.TRANSIENT))
    body = {"message": "Delivery time?", "conversation_id": conv_id}
    r = await c.post(f"{biz.pub}/chat/stream", json=body, headers=auth)
    assert r.status_code == 200
    events = _events(r.text)
    assert events[-1] == ("error", {"code": "agent_unavailable"})
    assert all(e != "done" for e, _ in events)
    seen = (await c.get(f"{biz.pub}/conversations/{conv_id}", headers=auth)).json()
    assert [m["content"] for m in seen["messages"]] == ["Hi", "Hello"]

    # Retry: the same message goes through once the provider answers.
    _primary(harness).replies.append("Two days.")
    r = await c.post(f"{biz.pub}/chat/stream", json=body, headers=auth)
    assert _events(r.text)[-1][1]["reply"] == "Two days."
    seen = (await c.get(f"{biz.pub}/conversations/{conv_id}", headers=auth)).json()
    assert [m["content"] for m in seen["messages"]] == ["Hi", "Hello", "Delivery time?",
                                                        "Two days."]  # fmt: skip


async def test_stream_errors_before_any_text_are_plain_http_errors(harness: AppHarness) -> None:
    biz = await _business(harness, public=True)
    c = harness.new_client()
    auth = {"X-Agentree-Guest": (await c.post(f"{biz.pub}/sessions")).json()["token"]}
    _primary(harness).replies.append(ErrorKind.UNAVAILABLE)
    r = await c.post(f"{biz.pub}/chat/stream", json={"message": "Hi"}, headers=auth)
    assert r.status_code == 503 and r.json()["detail"] == "agent_unavailable"
    r = await c.post(f"{biz.pub}/chat/stream", json={"message": "Hi",
                     "conversation_id": str(uuid.uuid4())}, headers=auth)  # fmt: skip
    assert r.status_code == 404
    r = await c.post(f"{biz.pub}/chat/stream", json={"message": "Hi"})
    assert r.status_code == 401

    _primary(harness).replies.append(ErrorKind.UNAVAILABLE)
    r = await biz.owner.client.post(f"{biz.console}/stream", json={"message": "Hi"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "ai_unavailable"


async def test_paused_conversation_streams_no_ai_reply(harness: AppHarness) -> None:
    biz = await _business(harness, public=True)
    c = harness.new_client()
    auth = {"X-Agentree-Guest": (await c.post(f"{biz.pub}/sessions")).json()["token"]}
    conv_id = (await c.post(f"{biz.pub}/chat", json={"message": "Hi"},
                            headers=auth)).json()["conversation_id"]  # fmt: skip
    await c.post(f"{biz.pub}/conversations/{conv_id}/handoff", headers=auth)
    calls = len(_primary(harness).calls)
    r = await c.post(f"{biz.pub}/chat/stream", headers=auth,
                     json={"message": "Anyone?", "conversation_id": conv_id})  # fmt: skip
    events = _events(r.text)
    assert events == [("done", {**events[0][1], "reply": "", "status": "needs_human"})]
    assert len(_primary(harness).calls) == calls


async def test_other_business_cannot_stream_in_the_console(harness: AppHarness) -> None:
    biz = await _business(harness)
    outsider = await signup(harness)
    r = await outsider.client.post(f"{biz.console}/stream", json={"message": "Hi"})
    assert r.status_code == 404


# --- monitoring -----------------------------------------------------------------------------

METRICS_TOKEN = "metrics-test-token-0123456789"  # noqa: S105


@pytest.fixture
async def metrics_client(settings: Any, mailer: FakeMailer) -> AsyncIterator[AsyncClient]:
    fakes = {name: FakeProvider(name=name) for name in ProviderName}
    app = create_app(
        settings.model_copy(update={"metrics_token": SecretStr(METRICS_TOKEN)}),
        mailer=mailer, llm_providers={n: _returning(f) for n, f in fakes.items()},
    )  # fmt: skip
    async with app.router.lifespan_context(app), _client(app) as c:
        yield c


async def test_metrics_need_the_token(harness: AppHarness, metrics_client: AsyncClient) -> None:
    disabled = harness.new_client()
    assert (await disabled.get("/api/internal/metrics")).status_code == 404  # no token set
    assert (await metrics_client.get("/api/internal/metrics")).status_code == 404
    r = await metrics_client.get("/api/internal/metrics",
                                 headers={"X-Agentree-Metrics-Token": "wrong"})  # fmt: skip
    assert r.status_code == 404
    r = await metrics_client.get("/api/internal/metrics",
                                 headers={"X-Agentree-Metrics-Token": METRICS_TOKEN})  # fmt: skip
    assert r.status_code == 200
    assert 'agentree_provider_keys{state="open"}' in r.text
    assert "# TYPE agentree_llm_calls_total counter" in r.text


async def test_metrics_count_calls_and_breaker_transitions(
    harness: AppHarness, metrics_client: AsyncClient
) -> None:
    opened = metrics.value("agentree_breaker_transitions_total", transition="opened")
    ok = metrics.value("agentree_llm_calls_total", provider="openai", slot="primary", outcome="ok")
    biz = await _business(harness)
    _primary(harness).replies.append("fine")
    await _ask(biz)
    _primary(harness).replies.append(ErrorKind.AUTH)
    await _ask(biz)
    assert metrics.value("agentree_llm_calls_total", provider="openai", slot="primary",
                         outcome="ok") == ok + 1  # fmt: skip
    assert metrics.value("agentree_breaker_transitions_total", transition="opened") == opened + 1
    r = await metrics_client.get("/api/internal/metrics",
                                 headers={"X-Agentree-Metrics-Token": METRICS_TOKEN})  # fmt: skip
    assert 'agentree_breaker_transitions_total{transition="opened"}' in r.text
    assert biz.id not in r.text  # counts only, never business ids
