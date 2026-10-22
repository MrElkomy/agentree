"""Bot challenge for public guest sessions (U-16): Cloudflare Turnstile.

A visitor's browser solves an invisible or managed Turnstile challenge and sends the one-time
token with the request that opens a guest session. The token is checked server-side against
Cloudflare's fixed siteverify URL (not a customer-supplied URL, so no SSRF guard is needed). A
token is accepted only for our own host and our own action name, so a token solved on another
site, or for another purpose, is refused.

Fail closed: when Cloudflare cannot be reached, no new guest session opens (existing sessions keep
working). The token and the secret are never logged.
"""

import logging
from enum import StrEnum
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
ACTION = "guest_session"  # the browser renders the widget with this action
MAX_TOKEN_LENGTH = 2048  # Turnstile tokens are at most 2048 characters
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class Verdict(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class BotChallenge(Protocol):
    @property
    def site_key(self) -> str | None:
        """Public site key for the browser widget; None when the challenge is off."""

    async def verify(self, token: str | None, remote_ip: str | None) -> Verdict: ...


class DisabledBotChallenge:
    """Development and tests without Turnstile keys: every request passes."""

    site_key = None

    async def verify(self, token: str | None, remote_ip: str | None) -> Verdict:
        return Verdict.PASSED


class TurnstileChallenge:
    def __init__(
        self,
        site_key: str,
        secret_key: str,
        hostname: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._site_key = site_key
        self._secret = secret_key
        self._hostname = hostname
        self._transport = transport

    @property
    def site_key(self) -> str | None:
        return self._site_key

    async def verify(self, token: str | None, remote_ip: str | None) -> Verdict:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return Verdict.FAILED
        form = {"secret": self._secret, "response": token}
        if remote_ip:
            form["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=TIMEOUT, follow_redirects=False
            ) as client:
                resp = await client.post(SITEVERIFY_URL, data=form)
            resp.raise_for_status()
            body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("bot challenge unavailable", extra={"error_type": type(exc).__name__})
            return Verdict.UNAVAILABLE
        if not isinstance(body, dict):
            return Verdict.UNAVAILABLE
        if (
            body.get("success") is True
            and body.get("hostname") == self._hostname
            and (body.get("action") == ACTION)
        ):
            return Verdict.PASSED
        codes = body.get("error-codes")
        logger.info("bot challenge failed", extra={
            "error_codes": [c for c in codes if isinstance(c, str)][:5]
            if isinstance(codes, list) else []})  # fmt: skip
        return Verdict.FAILED


def build_bot_challenge(
    site_key: str | None, secret_key: str | None, hostname: str
) -> BotChallenge:
    if site_key and secret_key:
        return TurnstileChallenge(site_key, secret_key, hostname)
    return DisabledBotChallenge()
