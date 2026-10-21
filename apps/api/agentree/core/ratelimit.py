"""Fixed-window rate limiting backed by PostgreSQL (no Redis in the MVP).

Keys must not contain personal data in clear text; hash identifiers such as emails.
"""

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_HIT = text(
    """
    INSERT INTO rate_limit_buckets AS b (key, window_start, count)
    VALUES (:key, now(), 1)
    ON CONFLICT (key) DO UPDATE SET
        count = CASE WHEN b.window_start <= now() - make_interval(secs => :window)
                     THEN 1 ELSE b.count + 1 END,
        window_start = CASE WHEN b.window_start <= now() - make_interval(secs => :window)
                            THEN now() ELSE b.window_start END
    RETURNING count
    """
)


def key_for(scope: str, identifier: str) -> str:
    digest = hashlib.sha256(identifier.lower().encode()).hexdigest()[:32]
    return f"{scope}:{digest}"


def daily_ai_budget_key(business_id: object, day: str) -> str:
    """One counter per business per UTC day for every AI call made for its visitors: chat
    replies and customer-memory extraction (the business's `daily_reply_budget`)."""
    return key_for("public-chat:business-day", f"{business_id}:{day}")


async def hit(
    factory: async_sessionmaker[AsyncSession], key: str, *, limit: int, window_seconds: int
) -> bool:
    """Record one attempt; return False when the limit for the window is exceeded."""
    async with factory() as session, session.begin():
        count = (await session.execute(_HIT, {"key": key, "window": window_seconds})).scalar_one()
    return int(count) <= limit
