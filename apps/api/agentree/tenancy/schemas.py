from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from agentree.tenancy.roles import Role


class BusinessCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=3, max_length=63)


class BusinessOut(BaseModel):
    id: UUID
    name: str
    slug: str
    role: Role


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    role: Role


class RoleChangeIn(BaseModel):
    role: Role


class InvitationCreateIn(BaseModel):
    email: EmailStr
    role: Role = Role.MEMBER


class InvitationOut(BaseModel):
    id: UUID
    email: str
    role: Role
    expires_at: datetime
    email_sent: bool | None = None  # set on creation; false means re-invite to retry


class AcceptInvitationIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)
