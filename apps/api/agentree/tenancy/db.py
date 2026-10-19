"""Tenant-scoped database access.

`tenant_session` is the only supported way to touch tenant tables. It opens one
transaction and binds the tenant with `set_config(..., is_local => true)`, so the
context is dropped automatically at commit or rollback and cannot leak to the next
user of a pooled connection (also safe behind transaction-mode poolers).

Worker rule: one `tenant_session` per job, built from the job's stored business id;
never reuse a session across jobs or tenants.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentree.tenancy.context import TenantContext


@asynccontextmanager
async def tenant_session(
    factory: async_sessionmaker[AsyncSession], ctx: TenantContext
) -> AsyncIterator[AsyncSession]:
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('agentree.business_id', :bid, true)"),
            {"bid": str(ctx.business_id)},
        )
        yield session
