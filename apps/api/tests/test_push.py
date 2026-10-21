"""Web Push: device opt-in, encrypted VAPID delivery, and alerts to Owners and Admins."""

import base64
import json
import os
import uuid
from typing import Any

import http_ece  # type: ignore[import-untyped]
import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from agentree.core.webpush import (
    InvalidSubscriptionError,
    Outcome,
    PushMessage,
    Subscription,
    WebPushSender,
    load_vapid_key,
    validate_subscription,
)
from agentree.llm.base import ErrorKind, ProviderName
from agentree.llm.fake import FakeProvider
from agentree.main import create_app
from agentree.providers import service as providers
from agentree.providers.outages import alert_provider_outages
from tests.conftest import AppHarness, FakeMailer, _returning
from tests.helpers import Account, create_business, invite_and_join, signup

KEY = "sk-push-primary-key-pppp1111"  # gitleaks:allow (fake test key)
BACKUP_KEY = "sk-push-backup-key-pppp2222"  # gitleaks:allow (fake test key)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Browser:
    """A browser's push subscription, with the receiver keys to decrypt what it gets."""

    def __init__(self, host: str = "fcm.googleapis.com") -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)
        self.endpoint = f"https://{host}/fcm/send/{uuid.uuid4().hex}"
        public = self.private_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        self.p256dh = _b64(public)

    def body(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": _b64(self.auth)},
                "expirationTime": None}  # fmt: skip

    def subscription(self) -> Subscription:
        return Subscription(self.endpoint, self.p256dh, _b64(self.auth))


# --- validation and keys ----------------------------------------------------------------------


@pytest.mark.parametrize("host", ["fcm.googleapis.com", "updates.push.services.mozilla.com",
                                  "web.push.apple.com", "wns2-par02p.notify.windows.com"])  # fmt: skip
def test_known_push_services_are_accepted(host: str) -> None:
    b = Browser(host)
    assert validate_subscription(b.endpoint, b.p256dh, _b64(b.auth)).endpoint == b.endpoint


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x",  # not https
    "https://fcm.googleapis.com.evil.example/x",  # look-alike host
    "https://evilfcm.googleapis.com.example/x",
    "https://localhost/x",
    "https://169.254.169.254/latest/meta-data",
    "https://fcm.googleapis.com:8443/x",  # unusual port
    "https://user:pw@fcm.googleapis.com/x",  # credentials in URL
    "https://example.com/push",
])  # fmt: skip
def test_other_endpoints_are_refused(endpoint: str) -> None:
    b = Browser()
    with pytest.raises(InvalidSubscriptionError):
        validate_subscription(endpoint, b.p256dh, _b64(b.auth))


def test_bad_keys_are_refused() -> None:
    b = Browser()
    with pytest.raises(InvalidSubscriptionError):
        validate_subscription(b.endpoint, _b64(b"not a point"), _b64(b.auth))
    with pytest.raises(InvalidSubscriptionError):
        validate_subscription(b.endpoint, b.p256dh, _b64(b"short"))


def test_vapid_key_from_openssl_der_and_pem() -> None:
    # Same format as `openssl ecparam -name prime256v1 -genkey -noout -outform DER | base64 -w0`.
    der = base64.b64encode(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )).decode()  # fmt: skip
    assert load_vapid_key(der).curve.name == "secp256r1"
    pem = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()  # fmt: skip
    assert load_vapid_key(pem).curve.name == "secp256r1"
    wrong = ec.generate_private_key(ec.SECP384R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()  # fmt: skip
    with pytest.raises(ValueError, match="P-256"):
        load_vapid_key(wrong)
    rsa_pem = rsa.generate_private_key(65537, 2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()  # fmt: skip
    with pytest.raises(ValueError):
        load_vapid_key(rsa_pem)
    with pytest.raises(ValueError):
        load_vapid_key("not a key")


# --- delivery ---------------------------------------------------------------------------------

MESSAGE = PushMessage(title="New lead for Acme", body="Tap to follow up.", url="/b/x/leads/y",
                      tag="lead-y")  # fmt: skip


def _sender(handler: Any) -> WebPushSender:
    return WebPushSender(ec.generate_private_key(ec.SECP256R1()), "mailto:ops@example.com",
                         transport=httpx.MockTransport(handler))  # fmt: skip


async def test_delivery_is_encrypted_and_vapid_signed() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201)

    browser = Browser()
    sender = _sender(handler)
    assert await sender.send(browser.subscription(), MESSAGE) is Outcome.SENT
    req = seen[0]
    assert str(req.url) == browser.endpoint
    assert req.headers["content-encoding"] == "aes128gcm"
    assert req.headers["ttl"] == "86400"
    auth = req.headers["authorization"]
    assert auth.startswith("vapid t=") and f"k={sender.public_key}" in auth
    token = auth.split("t=", 1)[1].split(",", 1)[0]
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert (
        claims["aud"] == "https://fcm.googleapis.com" and claims["sub"] == "mailto:ops@example.com"
    )
    assert b"New lead" not in req.content  # encrypted on the wire
    plain = http_ece.decrypt(req.content, private_key=browser.private_key,
                             auth_secret=browser.auth, version="aes128gcm")  # fmt: skip
    assert json.loads(plain) == {"title": "New lead for Acme", "body": "Tap to follow up.",
                                 "url": "/b/x/leads/y", "tag": "lead-y"}  # fmt: skip


@pytest.mark.parametrize(("status", "outcome"), [(410, Outcome.GONE), (404, Outcome.GONE),
                                                 (500, Outcome.FAILED), (301, Outcome.FAILED),
                                                 (429, Outcome.FAILED)])  # fmt: skip
async def test_delivery_outcomes(status: int, outcome: Outcome) -> None:
    sender = _sender(lambda r: httpx.Response(status, headers={"location": "https://evil.example"}))
    assert await sender.send(Browser().subscription(), MESSAGE) is outcome


async def test_network_errors_fail_quietly_and_bad_endpoints_are_never_contacted() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    assert await _sender(boom).send(Browser().subscription(), MESSAGE) is Outcome.FAILED
    calls: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(201)

    sender = _sender(record)
    b = Browser()
    with pytest.raises(InvalidSubscriptionError):
        await sender.send(Subscription("https://evil.example/x", b.p256dh, _b64(b.auth)), MESSAGE)
    assert calls == []


# --- opt-in API -------------------------------------------------------------------------------


class Biz:
    def __init__(self, owner: Account, business: dict[str, Any]) -> None:
        self.owner, self.id, self.slug = owner, business["id"], business["slug"]
        self.base = f"/api/businesses/{self.id}"
        self.push = f"{self.base}/notifications/push"
        self.pub = f"/api/public/{self.slug}"


async def _business(h: AppHarness, *, public: bool = False, backup: bool = False) -> Biz:
    owner = await signup(h)
    biz = Biz(owner, await create_business(owner, "Juniper Rugs"))
    r = await owner.client.put(f"{biz.base}/ai-providers/primary", json={
        "provider": "openai", "model": "gpt-4o-mini", "api_key": KEY, "verify": False})  # fmt: skip
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


async def _subscribe(acc: Account, biz: Biz, browser: Browser | None = None) -> Browser:
    browser = browser or Browser()
    r = await acc.client.post(f"{biz.push}/subscriptions", json=browser.body())
    assert r.status_code == 204, r.text
    return browser


async def test_owner_turns_alerts_on_and_off_for_a_device(harness: AppHarness) -> None:
    biz = await _business(harness)
    r = await biz.owner.client.get(biz.push)
    assert r.json() == {"available": True, "public_key": harness.push.public_key, "devices": 0}
    phone = await _subscribe(biz.owner, biz)
    await _subscribe(biz.owner, biz, phone)  # the same device again: still one
    await _subscribe(biz.owner, biz)
    assert (await biz.owner.client.get(biz.push)).json()["devices"] == 2

    r = await biz.owner.client.post(f"{biz.push}/test")
    assert r.status_code == 200 and r.json() == {"sent": 2}
    assert all(m.tag == "agentree-test" for _, m in harness.push.sent)

    r = await biz.owner.client.post(f"{biz.push}/subscriptions/check",
                                    json={"endpoint": phone.endpoint})  # fmt: skip
    assert r.json() == {"subscribed": True}
    r = await biz.owner.client.post(f"{biz.push}/subscriptions/remove",
                                    json={"endpoint": phone.endpoint})  # fmt: skip
    assert r.status_code == 204
    assert (await biz.owner.client.get(biz.push)).json()["devices"] == 1
    r = await biz.owner.client.post(f"{biz.push}/subscriptions/check",
                                    json={"endpoint": phone.endpoint})  # fmt: skip
    assert r.json() == {"subscribed": False}


async def test_only_admins_subscribe_and_bad_subscriptions_are_refused(harness: AppHarness) -> None:
    biz = await _business(harness)
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    r = await member.client.post(f"{biz.push}/subscriptions", json=Browser().body())
    assert r.status_code == 403
    assert (await member.client.get(biz.push)).status_code == 200  # can see availability
    bad = Browser().body() | {"endpoint": "https://attacker.example/collect"}
    r = await biz.owner.client.post(f"{biz.push}/subscriptions", json=bad)
    assert r.status_code == 422 and r.json()["detail"] == "invalid_push_subscription"
    outsider = await signup(harness)
    r = await outsider.client.post(f"{biz.push}/subscriptions", json=Browser().body())
    assert r.status_code == 404


async def test_push_unavailable_without_vapid_key(settings: Any, mailer: FakeMailer) -> None:
    fakes = {name: FakeProvider(name=name) for name in ProviderName}
    app = create_app(settings, mailer=mailer,
                     llm_providers={n: _returning(f) for n, f in fakes.items()})  # fmt: skip
    async with app.router.lifespan_context(app):
        h = AppHarness(app, mailer, [], fakes)
        try:
            biz = await _business(h)
            r = await biz.owner.client.get(biz.push)
            assert r.json()["available"] is False and r.json()["public_key"] is None
            r = await biz.owner.client.post(f"{biz.push}/subscriptions", json=Browser().body())
            assert r.status_code == 409 and r.json()["detail"] == "push_unavailable"
        finally:
            for c in h.clients:
                await c.aclose()


# --- alerts -------------------------------------------------------------------------------------


async def _guest(c: httpx.AsyncClient, biz: Biz) -> dict[str, str]:
    return {"X-Agentree-Guest": (await c.post(f"{biz.pub}/sessions")).json()["token"]}


async def test_new_lead_and_handoff_alert_admin_devices_without_customer_data(
    harness: AppHarness,
) -> None:
    biz = await _business(harness, public=True)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    demoted = await invite_and_join(harness, biz.owner, biz.id, "admin")
    owner_phone = await _subscribe(biz.owner, biz)
    admin_laptop = await _subscribe(admin, biz)
    demoted_phone = await _subscribe(demoted, biz)
    r = await biz.owner.client.patch(f"{biz.base}/members/{demoted.id}", json={"role": "member"})
    assert r.status_code == 200, r.text

    c = harness.new_client()
    auth = await _guest(c, biz)
    harness.llm[ProviderName.OPENAI].replies.append("Happy to help.")
    conv = (await c.post(f"{biz.pub}/chat", json={"message": "I'm Mona, mona@example.com"},
                         headers=auth)).json()["conversation_id"]  # fmt: skip
    r = await c.post(f"{biz.pub}/leads", headers=auth, json={
        "conversation_id": conv, "name": "Mona", "email": "mona@example.com", "need": "Wool rug",
        "consent": True, "idempotency_key": uuid.uuid4().hex})  # fmt: skip
    assert r.status_code == 200, r.text
    lead_pushes = [(e, m) for e, m in harness.push.sent if m.tag.startswith("lead-")]
    assert sorted(e for e, _ in lead_pushes) == sorted([owner_phone.endpoint,
                                                        admin_laptop.endpoint])  # fmt: skip
    assert demoted_phone.endpoint not in [e for e, _ in harness.push.sent]
    message = lead_pushes[0][1]
    assert message.title == "New lead for Juniper Rugs"
    assert message.url.startswith(f"/b/{biz.id}/leads/")
    assert "Mona" not in str(message) and "mona@" not in str(message) and "rug" not in str(message)

    harness.push.sent.clear()
    r = await c.post(f"{biz.pub}/conversations/{conv}/handoff", headers=auth)
    assert r.status_code == 200
    handoffs = [m for _, m in harness.push.sent if m.tag == f"handoff-{conv}"]
    assert len(handoffs) == 2 and handoffs[0].url == f"/b/{biz.id}/inbox/{conv}"


async def test_expired_devices_are_forgotten(harness: AppHarness) -> None:
    biz = await _business(harness)
    gone = await _subscribe(biz.owner, biz)
    alive = await _subscribe(biz.owner, biz)
    harness.push.outcomes[gone.endpoint] = Outcome.GONE
    r = await biz.owner.client.post(f"{biz.push}/test")
    assert r.json() == {"sent": 1}
    assert (await biz.owner.client.get(biz.push)).json()["devices"] == 1
    assert [e for e, _ in harness.push.sent] == [alive.endpoint]


async def test_devices_of_another_business_get_nothing(harness: AppHarness) -> None:
    a = await _business(harness, public=True)
    b = await _business(harness)
    # The same person owns B and subscribes there; A's alerts must not reach B's device.
    r = await a.owner.client.post(f"{a.base}/invitations",
                                  json={"email": b.owner.email, "role": "admin"})  # fmt: skip
    assert r.status_code == 201
    token = harness.mailer.token_for(b.owner.email)
    assert (await b.owner.client.post("/api/invitations/accept",
                                      json={"token": token})).status_code == 200  # fmt: skip
    b_device = await _subscribe(b.owner, b)
    c = harness.new_client()
    auth = await _guest(c, a)
    conv = (await c.post(f"{a.pub}/chat", json={"message": "hi"}, headers=auth)).json()
    await c.post(f"{a.pub}/conversations/{conv['conversation_id']}/handoff", headers=auth)
    assert b_device.endpoint not in [e for e, _ in harness.push.sent]


# --- provider outage alerts ---------------------------------------------------------------------


async def _break_primary(h: AppHarness, biz: Biz) -> None:
    for _ in range(providers.FAILURE_THRESHOLD):
        h.llm[ProviderName.OPENAI].replies.append(ErrorKind.UNAVAILABLE)
        h.llm[ProviderName.ANTHROPIC].replies.append("backup reply")
        await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={"message": "hi"})


async def test_outage_alert_once_per_outage_by_email_and_push(harness: AppHarness) -> None:
    biz = await _business(harness, backup=True)
    admin = await invite_and_join(harness, biz.owner, biz.id, "admin")
    member = await invite_and_join(harness, biz.owner, biz.id, "member")
    device = await _subscribe(admin, biz)
    st = harness.app.state
    await _break_primary(harness, biz)

    sent_before = len(harness.mailer.sent)
    assert await alert_provider_outages(st.session_factory, st.settings, st.mailer, st.push) >= 1
    emails = [m for m in harness.mailer.sent[sent_before:] if "Juniper Rugs" in m.subject]
    assert sorted(m.to for m in emails) == sorted([biz.owner.email, admin.email])
    assert member.email not in [m.to for m in emails]
    assert all("primary AI key is down" in m.subject for m in emails)
    assert all("backup key is answering" in m.body for m in emails)
    assert all(KEY not in m.body and KEY[-4:] not in m.body for m in emails)
    pushed = [m for e, m in harness.push.sent if e == device.endpoint]
    assert pushed[-1].title == "Juniper Rugs: primary AI key is down"
    assert pushed[-1].url == f"/b/{biz.id}/ai-providers"

    # The same outage is not alerted twice.
    count = len(harness.mailer.sent)
    await alert_provider_outages(st.session_factory, st.settings, st.mailer, st.push)
    assert len(harness.mailer.sent) == count


async def test_outage_without_backup_says_agents_cannot_answer(harness: AppHarness) -> None:
    biz = await _business(harness)
    harness.llm[ProviderName.OPENAI].replies.append(ErrorKind.AUTH)  # opens at once
    await biz.owner.client.post(f"{biz.base}/agents/sales/console", json={"message": "hi"})
    st = harness.app.state
    await alert_provider_outages(st.session_factory, st.settings, st.mailer, st.push)
    email = harness.mailer.last_to(biz.owner.email)
    assert "can't answer customers" in email.body
    assert "rejected the key" in email.body


async def test_recovered_key_is_not_alerted(harness: AppHarness) -> None:
    biz = await _business(harness, backup=True)
    await _break_primary(harness, biz)
    harness.llm[ProviderName.OPENAI].replies.append("OK")
    r = await biz.owner.client.post(f"{biz.base}/ai-providers/primary/test")
    assert r.json()["ok"] is True  # closes the breaker before the worker runs
    st = harness.app.state
    count = len(harness.mailer.sent)
    await alert_provider_outages(st.session_factory, st.settings, st.mailer, st.push)
    assert [m for m in harness.mailer.sent[count:] if "Juniper Rugs" in m.subject] == []
