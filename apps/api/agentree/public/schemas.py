from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentree.public.service import (
    MAX_BIO,
    MAX_DISPLAY_NAME,
    MAX_GUEST_MESSAGE,
    MAX_LINK_DESCRIPTION,
    MAX_LINK_LABEL,
    MAX_LINK_URL,
    MAX_LINKS,
    MAX_ORIGIN,
    MAX_ORIGINS,
    MAX_REPLY_BUDGET,
    InvalidLinkError,
    validate_link_url,
)

# --- owner (dashboard) ------------------------------------------------------------------


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LINK_LABEL)
    url: str = Field(min_length=1, max_length=MAX_LINK_URL)
    description: str = Field(default="", max_length=MAX_LINK_DESCRIPTION)

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label must not be blank")
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        return " ".join(v.split())  # one line on the page

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        try:
            return validate_link_url(v)
        except InvalidLinkError:
            raise ValueError("url must be an https:// URL") from None


class LinkOut(BaseModel):
    label: str
    url: str
    description: str


class PublicProfileIn(BaseModel):
    """Full replacement of the business's public page settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    display_name: str | None = Field(default=None, max_length=MAX_DISPLAY_NAME)
    bio: str = Field(default="", max_length=MAX_BIO)
    links: list[LinkIn] = Field(default_factory=list, max_length=MAX_LINKS)
    # Exact origins (https://host[:port]); normalized and validated by the service.
    widget_origins: list[Annotated[str, Field(min_length=1, max_length=MAX_ORIGIN)]] = Field(
        default_factory=list, max_length=MAX_ORIGINS
    )
    daily_reply_budget: int = Field(default=200, ge=1, le=MAX_REPLY_BUDGET)

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


class PublicProfileOut(BaseModel):
    slug: str
    enabled: bool
    display_name: str | None
    bio: str
    links: list[LinkOut]
    widget_origins: list[str]
    daily_reply_budget: int
    updated_at: datetime | None


# --- public (anonymous visitors) --------------------------------------------------------


class PublicPageOut(BaseModel):
    slug: str
    display_name: str
    bio: str
    links: list[LinkOut]
    chat_enabled: bool


class WidgetConfigOut(BaseModel):
    widget_origins: list[str]


class GuestSessionOut(BaseModel):
    token: str
    expires_at: datetime


class GuestChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_GUEST_MESSAGE)
    conversation_id: UUID | None = None
    channel: Literal["public", "widget"] = "public"

    @field_validator("message")
    @classmethod
    def _message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


class GuestChatOut(BaseModel):
    conversation_id: UUID
    reply: str


class GuestMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime
