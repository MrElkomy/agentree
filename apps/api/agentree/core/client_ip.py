"""Client IP for rate limiting, honouring only a configured number of trusted proxies."""

from ipaddress import IPv6Address, ip_address, ip_network

from starlette.requests import Request


def rate_limit_bucket(ip: str) -> str:
    """The unit a per-IP rate limit counts: the address for IPv4, its /64 network for IPv6.

    One IPv6 subscriber or server usually holds a whole /64, so counting single IPv6 addresses
    would let one client rotate through billions of buckets.
    """
    try:
        address = ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ip_network(f"{address}/64", strict=False))
    return str(address)


def client_ip(request: Request, trusted_proxy_count: int) -> str:
    """Return the client address as seen by the outermost trusted proxy.

    Each trusted proxy appends the address it received the request from to X-Forwarded-For,
    so the entry `trusted_proxy_count` positions from the right is the one the outermost
    proxy recorded. Entries further left are client-supplied and never trusted.
    """
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_count == 0:
        return peer
    entries = [e.strip() for e in ",".join(request.headers.getlist("x-forwarded-for")).split(",")]
    entries = [e for e in entries if e]
    if len(entries) < trusted_proxy_count:
        return peer  # misconfigured or bypassed proxy: fall back to the TCP peer
    candidate = entries[-trusted_proxy_count]
    try:
        return str(ip_address(candidate))
    except ValueError:
        return peer
