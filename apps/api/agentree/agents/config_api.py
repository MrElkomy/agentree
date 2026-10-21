"""Agent configuration for business members (Task 14): read for all, change for Admins+."""

from fastapi import APIRouter, HTTPException, Request, status

from agentree.agents import configs
from agentree.agents.registry import AgentRole
from agentree.agents.schemas import AgentConfigIn, AgentConfigOut
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/agents", tags=["agents"])


def _out(c: configs.AgentConfigInfo) -> AgentConfigOut:
    d = c.definition
    return AgentConfigOut(
        role=c.role, title=d.title, name=c.name, display_name=c.display_name,
        audience=d.audience, handles=d.handles, available=d.available, enabled=c.enabled,
        public=c.public, tools=sorted(c.tools), available_tools=sorted(d.tools),
        version=c.version, updated_at=c.updated_at,
    )  # fmt: skip


@router.get("")
async def list_agents(member: Member, request: Request) -> list[AgentConfigOut]:
    roster = await configs.roster(request.app.state.session_factory, member.tenant)
    return [_out(c) for c in roster.all()]


@router.put("/{role}")
async def update_agent(
    role: AgentRole, body: AgentConfigIn, member: Member, request: Request
) -> AgentConfigOut:
    member.require(Role.ADMIN)
    try:
        saved = await configs.update_config(
            request.app.state.session_factory, member.tenant, role, enabled=body.enabled,
            display_name=body.display_name, public=body.public, tools=body.tools,
            actor_id=member.user.id,
        )  # fmt: skip
    except configs.AgentNotAvailableError:
        raise HTTPException(status.HTTP_409_CONFLICT, "agent_not_available") from None
    except configs.InvalidAgentConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid_{exc}") from None
    return _out(saved)
