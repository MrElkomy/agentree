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
    # "Remember customers": email code, memory extraction (counts toward the daily budget).
    customer_memory: bool = True

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
    customer_memory: bool
    updated_at: datetime | None


# --- public (anonymous visitors) --------------------------------------------------------


class PublicAgentOut(BaseModel):
    role: str
    name: str  # display name (cosmetic)


class PublicPageOut(BaseModel):
    slug: str
    display_name: str
    bio: str
    links: list[LinkOut]
    chat_enabled: bool
    agents: list[PublicAgentOut]  # enabled agents visitors can start a chat with, in order
    lead_capture: bool  # the "Leave your details" form is available
    # Days chats and what the agents remember about a visitor are kept (shown to visitors).
    retention_days: int = 30
    customer_memory: bool = True  # "Remember me" is offered (the business remembers customers)


class IdentityOut(BaseModel):
    """Whether this browser's guest session is a verified customer (Task 16)."""

    verified: bool
    email_hint: str | None = None  # masked, e.g. "m***@example.com"


class IdentityStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)


class IdentityStartOut(BaseModel):
    sent: bool  # always true when accepted: never reveals whether the email is known


class IdentityConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^\s*\d{6}\s*$")


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
    # Agent to start a new conversation with (one of the page's `agents`); default: the first.
    agent: str | None = Field(default=None, max_length=32)

    @field_validator("message")
    @classmethod
    def _message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


class LeadSuggestionOut(BaseModel):
    """Prefill for the visitor's confirmation form (only details the visitor wrote)."""

    name: str
    email: str
    phone: str
    need: str


ConversationStatus = Literal["open", "needs_human", "human_active", "resolved"]


class GuestReplyOut(BaseModel):
    agent: str
    agent_name: str
    content: str


class GuestChatOut(BaseModel):
    conversation_id: UUID
    # Empty while a person handles the conversation (the AI does not answer then).
    reply: str
    lead_suggestion: LeadSuggestionOut | None = None
    status: ConversationStatus = "open"
    agent: str | None = None  # the agent now handling the conversation
    agent_name: str | None = None
    replies: list[GuestReplyOut] = []  # every agent reply of this turn (handoffs), in order
    can_resolve: bool = False  # the visitor may mark this conversation resolved (Customer Service)


class GuestConversationOut(BaseModel):
    """What the visitor's chat polls while waiting for, or talking to, a person."""

    status: ConversationStatus
    messages: list["GuestMessageOut"]
    can_resolve: bool = False


class GuestLeadIn(BaseModel):
    """Contact details the visitor confirmed. Consent is required and must be explicit."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    name: str = Field(default="", max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    need: str = Field(default="", max_length=500)
    consent: Literal[True]
    # Client-generated per form submission, so a retried request records the lead once.
    idempotency_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class GuestLeadOut(BaseModel):
    received: bool


class GuestMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime
    agent: str | None = None  # assistant messages: the agent's role
    agent_name: str | None = None
