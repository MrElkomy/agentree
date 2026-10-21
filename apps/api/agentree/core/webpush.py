"""Web Push delivery (RFC 8030/8291/8292): encrypted, VAPID-signed, to browser push services only.

Payload encryption (aes128gcm) and the VAPID signature come from `http_ece` and `py_vapid`; no
custom crypto here. A subscription endpoint is a URL supplied by the user's browser, so it is
untrusted: only https URLs on the browsers' own push services are accepted (an allowlist instead
of a general SSRF guard), and the endpoint is never logged (it acts as a delivery credential).
"""

import base64
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

import http_ece  # type: ignore[import-untyped]
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Push services of Chrome/Android, Firefox, Safari (macOS/iOS) and Edge.
PUSH_SERVICE_DOMAINS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)
TTL_SECONDS = 24 * 3600  # an alert older than a day is no longer useful
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_PAYLOAD = 2048


class InvalidSubscriptionError(ValueError):
    pass


class Outcome(StrEnum):
    SENT = "sent"
    GONE = "gone"  # unsubscribed or expired: delete the subscription
    FAILED = "failed"


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str  # base64url, the browser's P-256 public key
    auth: str  # base64url, 16-byte auth secret


@dataclass(frozen=True)
class PushMessage:
    title: str
    body: str
    url: str  # same-origin path opened on click, e.g. /b/{id}/leads/{lead_id}
    tag: str  # notifications with the same tag replace each other

    def payload(self) -> bytes:
        return json.dumps(
            {"title": self.title, "body": self.body, "url": self.url, "tag": self.tag},
            separators=(",", ":"),
        ).encode()


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def validate_subscription(endpoint: str, p256dh: str, auth: str) -> Subscription:
    """Accept only well-formed subscriptions on a known push service (else InvalidSubscription)."""
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or len(endpoint) > 1024
        or not any(host == d or host.endswith("." + d) for d in PUSH_SERVICE_DOMAINS)
    ):
        raise InvalidSubscriptionError("endpoint")
    try:
        key = _b64url_decode(p256dh)
        secret = _b64url_decode(auth)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)
    except (ValueError, TypeError):
        raise InvalidSubscriptionError("keys") from None
    if len(secret) != 16:
        raise InvalidSubscriptionError("keys")
    return Subscription(endpoint, p256dh, auth)


def load_vapid_key(value: str) -> ec.EllipticCurvePrivateKey:
    """The VAPID private key from PEM text or base64 DER (`openssl ecparam ... -outform DER`)."""
    text = value.strip()
    try:
        if text.startswith("-----BEGIN"):
            key = serialization.load_pem_private_key(text.encode(), password=None)
        else:
            key = serialization.load_der_private_key(base64.b64decode(text), password=None)
    except ValueError:
        raise ValueError("invalid VAPID private key") from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise ValueError("the VAPID key must be a P-256 (prime256v1) EC private key")
    return key


def application_server_key(private_key: ec.EllipticCurvePrivateKey) -> str:
    """Public key the browser needs to subscribe (base64url, uncompressed point)."""
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(raw)


class PushSender(Protocol):
    @property
    def public_key(self) -> str | None:
        """None when Web Push is not configured on this server."""
        ...

    async def send(self, subscription: Subscription, message: PushMessage) -> Outcome: ...


class DisabledPushSender:
    public_key: str | None = None

    async def send(self, subscription: Subscription, message: PushMessage) -> Outcome:
        return Outcome.FAILED


class WebPushSender:
    def __init__(
        self,
        private_key: ec.EllipticCurvePrivateKey,
        subject: str,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._vapid = Vapid02(private_key=private_key)
        self._subject = subject
        self._transport = transport
        self._clock = clock
        self.public_key: str | None = application_server_key(private_key)

    def _encrypt(self, subscription: Subscription, payload: bytes) -> bytes:
        sender_key = ec.generate_private_key(ec.SECP256R1())  # fresh per message
        data: bytes = http_ece.encrypt(
            payload,
            private_key=sender_key,
            dh=_b64url_decode(subscription.p256dh),
            auth_secret=_b64url_decode(subscription.auth),
            version="aes128gcm",
        )
        return data

    def _headers(self, endpoint: str) -> dict[str, str]:
        parts = urlsplit(endpoint)
        claims = {
            "sub": self._subject,
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(self._clock()) + 12 * 3600,
        }
        headers: dict[str, str] = self._vapid.sign(claims)
        return {
            **headers,
            "TTL": str(TTL_SECONDS),
            "Urgency": "high",
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
        }

    async def send(self, subscription: Subscription, message: PushMessage) -> Outcome:
        # Re-checked at send time: stored rows are trusted only as far as validation goes.
        validate_subscription(subscription.endpoint, subscription.p256dh, subscription.auth)
        payload = message.payload()
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("push payload too large")
        body = self._encrypt(subscription, payload)
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=TIMEOUT, follow_redirects=False
            ) as client:
                resp = await client.post(
                    subscription.endpoint,
                    content=body,
                    headers=self._headers(subscription.endpoint),
                )
        except httpx.HTTPError:
            logger.warning("web push delivery failed", extra={"reason": "network"})
            return Outcome.FAILED
        if resp.status_code in (404, 410):
            return Outcome.GONE
        if resp.status_code >= 300:
            # Never log the endpoint or the response body.
            logger.warning("web push delivery failed", extra={"status": resp.status_code})
            return Outcome.FAILED
        return Outcome.SENT


def build_push_sender(private_key: str | None, subject: str) -> PushSender:
    if not private_key:
        return DisabledPushSender()
    return WebPushSender(load_vapid_key(private_key), subject)
