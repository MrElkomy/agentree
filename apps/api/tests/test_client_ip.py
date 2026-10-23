"""Client IP resolution behind trusted reverse proxies (rate limiting keys)."""

import pytest
from starlette.requests import Request

from agentree.core.client_ip import client_ip, rate_limit_bucket
from agentree.core.config import Settings
from agentree.main import create_app
from tests.conftest import WEB_ORIGIN, FakeMailer, running_app
from tests.helpers import PASSWORD, unique_email


def _request(peer: str, *xff: str) -> Request:
    headers = [(b"x-forwarded-for", v.encode()) for v in xff]
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_without_trusted_proxies_the_header_is_ignored() -> None:
    assert client_ip(_request("172.18.0.5", "203.0.113.9"), 0) == "172.18.0.5"


def test_one_trusted_proxy_uses_the_rightmost_entry() -> None:
    # Caddy appends the real client; anything to its left was sent by the client.
    req = _request("172.18.0.5", "6.6.6.6, 203.0.113.9")
    assert client_ip(req, 1) == "203.0.113.9"


def test_entries_from_repeated_headers_are_combined() -> None:
    assert client_ip(_request("172.18.0.5", "6.6.6.6", "203.0.113.9"), 1) == "203.0.113.9"


def test_two_trusted_proxies() -> None:
    assert client_ip(_request("10.0.0.2", "6.6.6.6, 203.0.113.9, 10.0.0.1"), 2) == "203.0.113.9"


@pytest.mark.parametrize("xff", [(), ("",), ("not-an-ip",)])
def test_missing_or_invalid_header_falls_back_to_the_peer(xff: tuple[str, ...]) -> None:
    assert client_ip(_request("172.18.0.5", *xff), 1) == "172.18.0.5"


def test_ipv6_is_normalised() -> None:
    assert client_ip(_request("172.18.0.5", "2001:DB8::0001"), 1) == "2001:db8::1"


async def test_rate_limit_is_per_forwarded_client(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"trusted_proxy_count": 1}), mailer=FakeMailer())
    async with running_app(app) as c:

        async def register(ip: str) -> int:
            body = {"email": unique_email(), "password": PASSWORD}
            headers = {"X-Forwarded-For": f"6.6.6.6, {ip}", "Origin": WEB_ORIGIN}
            return (await c.post("/api/auth/register", json=body, headers=headers)).status_code

        codes = [await register("198.51.100.7") for _ in range(11)]
        assert codes == [202] * 10 + [429]
        # Another client behind the same proxy is not affected.
        assert await register("198.51.100.8") == 202


@pytest.mark.parametrize(("ip", "bucket"), [
    ("203.0.113.9", "203.0.113.9"),
    ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
    ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),  # same /64, same bucket
    ("::ffff:203.0.113.9", "203.0.113.9"),  # IPv4-mapped counts as the IPv4 address
    ("unknown", "unknown"),
])  # fmt: skip
def test_ipv6_rate_limits_count_the_64_network(ip: str, bucket: str) -> None:
    assert rate_limit_bucket(ip) == bucket
