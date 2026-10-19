"""Membership-based authorization for business-scoped routes.

The `business_id` path parameter only *selects* a business; the membership lookup
*authorizes* it. Non-members get 404 (no existence disclosure).
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from agentree.identity.deps import VerifiedUser
from agentree.identity.service import AuthenticatedUser
from agentree.tenancy.context import TenantContext, TenantSource
from agentree.tenancy.roles import Role, at_least
from agentree.tenancy.service import membership_role


@dataclass(frozen=True)
class MemberContext:
    tenant: TenantContext
    user: AuthenticatedUser
    role: Role

    def require(self, minimum: Role) -> None:
        if not at_least(self.role, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_role")


async def member_context(business_id: UUID, request: Request, user: VerifiedUser) -> MemberContext:
    role = await membership_role(request.app.state.session_factory, user.id, business_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return MemberContext(TenantContext(business_id, TenantSource.MEMBERSHIP), user, role)


Member = Annotated[MemberContext, Depends(member_context)]
