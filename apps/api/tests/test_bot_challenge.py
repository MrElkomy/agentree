"""Bot challenge on new public guest sessions (Task 22, U-16): Cloudflare Turnstile tokens are
checked server-side, for our host and action only; failures and outages open no session, and
unsolved requests cannot use up a business's daily sessions."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from agentree.core.botcheck import (
    ACTION,
    SITEVERIFY_URL,
    DisabledBotChallenge,
    TurnstileChallenge,
    Verdict,
)
from agentree.public import service as public
from tests.conftest import AppHarness
from tests.test_agents import Biz
from tests.test_support_agents import _support_business

HOST = "app.agentree.test"
SOLVED = "solved"


def _turnstile(reply: object, status: int = 200, seen: list[dict[str, list[str]]] | None = None
               ) -> TurnstileChallenge:  # fmt: skip
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == SITEVERIFY_URL
        if seen is not None:
            seen.append(parse_qs(request.content.decode()))
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(status, content=json.dumps(reply).encode())

    return TurnstileChallenge("site-key", "secret-key", HOST, httpx.MockTransport(handle))


def _ok(**over: object) -> dict[str, object]:
    return {"success": True, "hostname": HOST, "action": ACTION, "error-codes": []} | over


# --- verifier -----------------------------------------------------------------------------------


async def test_a_valid_token_passes_and_the_secret_goes_only_to_cloudflare() -> None:
    seen: list[dict[str, list[str]]] = []
    assert await _turnstile(_ok(), seen=seen).verify("tok", "203.0.113.9") is Verdict.PASSED
    assert seen == [{"secret": ["secret-key"], "response": ["tok"], "remoteip": ["203.0.113.9"]}]


@pytest.mark.parametrize("reply", [
    {"success": False, "error-codes": ["invalid-input-response"]},
    _ok(hostname="evil.example"),  # solved on another site
    _ok(action="login"),  # solved for another purpose
    _ok(success="true"),
])  # fmt: skip
async def test_bad_tokens_fail(reply: dict[str, object]) -> None:
    assert await _turnstile(reply).verify("tok", None) is Verdict.FAILED


@pytest.mark.parametrize("token", [None, "", "x" * 2049])
async def test_missing_or_oversized_tokens_fail_without_a_call(token: str | None) -> None:
    seen: list[dict[str, list[str]]] = []
    assert await _turnstile(_ok(), seen=seen).verify(token, None) is Verdict.FAILED
    assert seen == []


@pytest.mark.parametrize(("reply", "status"), [
    (httpx.ConnectError("down"), 200), (_ok(), 500), ("not json", 200), ([1], 200),
])  # fmt: skip
async def test_cloudflare_trouble_is_unavailable(reply: object, status: int) -> None:
    assert await _turnstile(reply, status).verify("tok", None) is Verdict.UNAVAILABLE


async def test_a_non_json_answer_is_unavailable() -> None:
    challenge = TurnstileChallenge("s", "k", HOST, httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"<html>")))  # fmt: skip
    assert await challenge.verify("tok", None) is Verdict.UNAVAILABLE


# --- the public API -----------------------------------------------------------------------------


class FakeChallenge:
    site_key = "site-key"

    def __init__(self, verdict: Verdict = Verdict.PASSED) -> None:
        self.verdict = verdict
        self.tokens: list[str | None] = []

    async def verify(self, token: str | None, remote_ip: str | None) -> Verdict:
        self.tokens.append(token)
        if self.verdict is not Verdict.PASSED:
            return self.verdict
        return Verdict.PASSED if token == SOLVED else Verdict.FAILED


async def _with_challenge(h: AppHarness, verdict: Verdict = Verdict.PASSED) -> tuple[
    Biz, FakeChallenge
]:  # fmt: skip
    biz = await _support_business(h)
    fake = FakeChallenge(verdict)
    h.app.state.bot_challenge = fake
    return biz, fake


async def test_off_by_default_and_the_page_says_so(harness: AppHarness) -> None:
    assert isinstance(harness.app.state.bot_challenge, DisabledBotChallenge)
    biz = await _support_business(harness)
    c = harness.new_client()
    assert (await c.get(biz.pub)).json()["challenge_site_key"] is None
    assert (await c.post(f"{biz.pub}/sessions")).status_code == 201


async def test_a_session_needs_a_solved_challenge(harness: AppHarness) -> None:
    biz, fake = await _with_challenge(harness)
    c = harness.new_client()
    assert (await c.get(biz.pub)).json()["challenge_site_key"] == "site-key"
    r = await c.post(f"{biz.pub}/sessions")
    assert r.status_code == 403 and r.json()["detail"] == "challenge_failed"
    r = await c.post(f"{biz.pub}/sessions", json={"challenge": "wrong"})
    assert r.status_code == 403
    r = await c.post(f"{biz.pub}/sessions", json={"challenge": "solved"})
    assert r.status_code == 201 and r.json()["token"]
    assert fake.tokens == [None, "wrong", "solved"]
    r = await c.post(f"{biz.pub}/sessions", json={"challenge": "x" * 2049})
    assert r.status_code == 422


async def test_an_outage_opens_no_session(harness: AppHarness) -> None:
    biz, _ = await _with_challenge(harness, Verdict.UNAVAILABLE)
    r = await harness.new_client().post(f"{biz.pub}/sessions", json={"challenge": "solved"})
    assert r.status_code == 429 and r.json()["detail"] == "busy"


async def test_unsolved_requests_do_not_use_up_the_business_quota(
    harness: AppHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(public, "SESSIONS_PER_BUSINESS_PER_DAY", 2)
    biz, _ = await _with_challenge(harness)
    for _ in range(5):  # one IP, under its hourly limit
        assert (await harness.new_client().post(f"{biz.pub}/sessions")).status_code == 403
    for _ in range(2):
        r = await harness.new_client().post(f"{biz.pub}/sessions", json={"challenge": "solved"})
        assert r.status_code == 201
    r = await harness.new_client().post(f"{biz.pub}/sessions", json={"challenge": "solved"})
    assert r.status_code == 429
