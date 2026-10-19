from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class ResetConfirmIn(TokenIn):
    new_password: str = Field(max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class MeOut(BaseModel):
    id: UUID
    email: str
    email_verified: bool


class StatusOut(BaseModel):
    status: str
