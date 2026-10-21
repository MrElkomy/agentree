"""The five approved agent roles: fixed, versioned definitions owned by Agentree.

A business configures its agents (enabled, display name, public access, tools) in
`agent_configs`; it never changes what a role is. Role identity, audience and the tool allowlist
come only from here and from the Action Gateway: never from model output, display names or
client input. Bump `version` when a role's behaviour or prompt changes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from agentree.actions.service import PERMISSIONS, Action


class AgentRole(StrEnum):
    SALES = "sales"
    CUSTOMER_SERVICE = "customer_service"
    TECHNICAL_SUPPORT = "technical_support"
    DATA_ANALYST = "data_analyst"
    EXECUTIVE = "executive"


class Audience(StrEnum):
    PUBLIC = "public"  # may talk with visitors (public page, widget) when the business allows
    INTERNAL = "internal"  # business members only; never reachable by a guest


@dataclass(frozen=True)
class AgentDefinition:
    role: AgentRole
    version: int
    title: str  # default name shown when the business sets no display name
    audience: Audience
    handles: str  # what the role is for: shown to owners and to teammates when routing
    available: bool  # implemented enough to be enabled (later tasks complete the others)
    enabled_by_default: bool
    # Approved PO decisions (Task 15; Technical Support added 2026-10-22): conversations this
    # agent leads may be marked resolved by the visitor and (with the resolve tool) by the
    # agent, not only by the team. Sales stays team-only.
    shared_resolution: bool = False
    # Customer memory categories (agentree.customers) this role may read about a verified
    # customer (Task 16). Fixed here; nothing else widens it.
    memory: frozenset[str] = frozenset()

    @property
    def tools(self) -> frozenset[Action]:
        """The role's Action Gateway allowlist (the business can only narrow it)."""
        return PERMISSIONS.get(self.role, frozenset())


DEFINITIONS: Mapping[AgentRole, AgentDefinition] = {
    d.role: d
    for d in (
        AgentDefinition(
            AgentRole.SALES, 3, "Sales Agent", Audience.PUBLIC,
            "products, services, prices, quotes and buying", available=True,
            enabled_by_default=True,
            memory=frozenset({"interest", "owned", "preference", "constraint"}),
        ),
        # Task 15: complete agents. Off until the business turns them on.
        AgentDefinition(
            AgentRole.CUSTOMER_SERVICE, 3, "Customer Service", Audience.PUBLIC,
            "general questions, company policies, service information, orders, accounts and "
            "complaints", available=True, enabled_by_default=False, shared_resolution=True,
            memory=frozenset({"owned", "issue", "preference"}),
        ),
        AgentDefinition(
            AgentRole.TECHNICAL_SUPPORT, 3, "Technical Support", Audience.PUBLIC,
            "setup, troubleshooting, errors and how-to questions", available=True,
            enabled_by_default=False, shared_resolution=True,
            memory=frozenset({"owned", "issue"}),
        ),
        # Internal roles: built in Tasks 18 and 20. They can never be enabled for guests.
        AgentDefinition(
            AgentRole.DATA_ANALYST, 1, "Data Analyst", Audience.INTERNAL,
            "analysis of the business's own data", available=False, enabled_by_default=False,
        ),
        AgentDefinition(
            AgentRole.EXECUTIVE, 1, "Executive Assistant", Audience.INTERNAL,
            "business overview, reports and managing the AI team", available=False,
            enabled_by_default=False,
        ),
    )
}  # fmt: skip

ROLES = tuple(DEFINITIONS)


def definition(role: str) -> AgentDefinition | None:
    """The definition of a known role, else None (unknown names are never trusted)."""
    try:
        return DEFINITIONS[AgentRole(role)]
    except ValueError:
        return None
