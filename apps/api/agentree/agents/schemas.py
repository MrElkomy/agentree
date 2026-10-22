from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ConsoleMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None
    # Entry agent of a new conversation (role); default: the first enabled agent.
    agent: str | None = Field(default=None, max_length=32)


class AgentReplyOut(BaseModel):
    agent: str  # role
    agent_name: str
    content: str


class HandoffOut(BaseModel):
    from_agent: str
    to_agent: str


class SourceOut(BaseModel):
    id: UUID
    title: str


class ConsoleReplyOut(BaseModel):
    conversation_id: UUID
    reply: str
    sources: list[SourceOut]
    provider: str
    model: str
    slot: str
    fallback_used: bool
    agent: str  # answered last; now the conversation's active agent
    agent_name: str
    replies: list[AgentReplyOut]  # every agent reply of this turn, in order
    handoffs: list[HandoffOut]


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    agent: str | None = None  # role of the agent that wrote an assistant message


# --- human inbox ------------------------------------------------------------------------------


class InboxItemOut(BaseModel):
    id: UUID
    channel: str
    status: Literal["open", "needs_human", "human_active", "resolved"]
    assignee_user_id: UUID | None
    handoff_reason: str | None
    handoff_requested_at: datetime | None
    last_message_at: datetime
    created_at: datetime
    preview: str
    preview_role: str


class InboxPageOut(BaseModel):
    items: list[InboxItemOut]
    counts: dict[str, int]
    next_before: datetime | None  # pass as `before` for older conversations; None at the end


class InboxMessageOut(BaseModel):
    id: UUID
    role: str  # user (visitor) | assistant (AI) | human (team member)
    author_user_id: UUID | None
    content: str
    created_at: datetime
    agent: str | None = None  # assistant messages: the agent's role


class InboxConversationOut(BaseModel):
    conversation: InboxItemOut
    messages: list[InboxMessageOut]


class InboxReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)


class InboxAssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: UUID | None


class AgentConfigOut(BaseModel):
    role: str
    title: str  # the role's default name
    name: str  # display name if set, else the title
    display_name: str
    audience: Literal["public", "internal"]
    handles: str
    available: bool  # false: built in a later update, cannot be enabled yet
    enabled: bool
    public: bool  # visitors can reach it (public roles only)
    tools: list[str]  # enabled tools (within available_tools)
    available_tools: list[str]  # the role's allowlist
    version: int  # 0 until the business first saves this agent
    updated_at: datetime | None
    availability: "AvailabilityOut"
    answering_now: bool  # visitors get AI replies now (false: its fixed message)


class AvailabilityOut(BaseModel):
    mode: Literal["always", "business_hours", "outside_business_hours"]
    away_message: str  # empty: the default message
    paused_from: datetime | None
    paused_until: datetime | None
    pause_message: str  # empty: the default message


class AvailabilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["always", "business_hours", "outside_business_hours"]
    away_message: str = Field(default="", max_length=500)
    paused_from: AwareDatetime | None = None
    paused_until: AwareDatetime | None = None
    pause_message: str = Field(default="", max_length=500)


class DayHoursIO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class BusinessHoursIO(BaseModel):
    """Monday first; null: closed. `configured` is false until the business saves its hours."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(max_length=64)
    days: list[DayHoursIO | None] = Field(min_length=7, max_length=7)
    configured: bool = True


class AgentConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    display_name: str = Field(default="", max_length=80)
    public: bool
    tools: list[str] = Field(default_factory=list, max_length=20)
