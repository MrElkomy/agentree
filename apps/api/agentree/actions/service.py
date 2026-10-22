"""Action Gateway: the only path by which an agent changes business data.

Every agent action is (1) authorized against a fixed per-role allowlist enforced here in the
backend, never by the model, narrowed by the tools the business enabled for that agent (Task 14),
and (2) idempotent: the first execution of an idempotency key is
recorded in the caller's transaction; a retry with the same key and parameters returns the
original result instead of acting twice, and the same key with different parameters is refused.
Model output never names the action or the agent: trusted server code does.

Sensitive actions (`APPROVALS`, Task 19) never run directly: they become approval requests
(`agentree.approvals`) that an Owner or Admin approves once or always, and run after that.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentree.actions.models import ActionExecution
from agentree.core.ids import uuid7
from agentree.tenancy.context import TenantContext


class Action(StrEnum):
    CREATE_LEAD = "create_lead"
    UPDATE_LEAD = "update_lead"
    CREATE_FOLLOW_UP_TASK = "create_follow_up_task"
    RESOLVE_CONVERSATION = "resolve_conversation"  # mark the visitor's conversation resolved
    SEND_FOLLOW_UP_EMAIL = "send_follow_up_email"  # email a lead a drafted follow-up (Task 19)


# Agent role -> actions it may run. Agents not listed may run nothing.
PERMISSIONS: Mapping[str, frozenset[Action]] = {
    "sales": frozenset(
        {
            Action.CREATE_LEAD,
            Action.UPDATE_LEAD,
            Action.CREATE_FOLLOW_UP_TASK,
            Action.SEND_FOLLOW_UP_EMAIL,
        }
    ),
    "customer_service": frozenset({Action.RESOLVE_CONVERSATION}),
    # PO decision 2026-10-22: support conversations too may be closed by the agent.
    "technical_support": frozenset({Action.RESOLVE_CONVERSATION}),
}

# Tools a business must turn on itself: off in an agent's default configuration.
OPT_IN: frozenset[Action] = frozenset({Action.SEND_FOLLOW_UP_EMAIL})


@dataclass(frozen=True)
class ApprovalPolicy:
    label: str  # what the agent wants to do, for people ("send a follow-up email")
    ttl: timedelta  # an unanswered request expires after this
    allow_always: bool  # an Owner/Admin may allow it permanently ("Always allow")


# Sensitive actions: they run only after a person approves (once, or always by rule).
APPROVALS: Mapping[Action, ApprovalPolicy] = {
    # PO decision 2026-10-21 (option B): agent-written follow-up messages are drafts the owner
    # approves; 2026-10-22: approve once or always.
    Action.SEND_FOLLOW_UP_EMAIL: ApprovalPolicy(
        "send a follow-up email to a lead", ttl=timedelta(days=3), allow_always=True
    ),
}

MAX_KEY_LEN = 100


class ActionDeniedError(Exception):
    pass


class IdempotencyConflictError(Exception):
    """The idempotency key was already used for a different action or parameters."""


def authorize(agent: str, action: Action, granted: frozenset[Action] | None = None) -> None:
    """`granted`: the tools the business enabled for this agent (None: the role's allowlist)."""
    if action not in PERMISSIONS.get(agent, frozenset()):
        raise ActionDeniedError(f"{agent} may not {action}")
    if granted is not None and action not in granted:
        raise ActionDeniedError(f"{action} is turned off for {agent}")


def requires_approval(action: Action) -> bool:
    return action in APPROVALS


def params_hash(params: Mapping[str, Any]) -> str:
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def claim(
    session: AsyncSession, ctx: TenantContext, *, agent: str, action: Action,
    idempotency_key: str, params: Mapping[str, Any], granted: frozenset[Action] | None = None,
) -> UUID | None:  # fmt: skip
    """Authorize and reserve an idempotency key inside the caller's transaction.

    Returns None when this call owns the key (the caller performs the action, then calls
    `complete`), or the result id of the earlier execution of the same request. A concurrent
    claim of the same key waits on the unique index until the first transaction finishes.
    """
    authorize(agent, action, granted)
    if requires_approval(action):  # only agentree.approvals runs these, after a person decides
        raise ActionDeniedError(f"{action} needs an approval")
    if not idempotency_key or len(idempotency_key) > MAX_KEY_LEN:
        raise ValueError("invalid idempotency key")
    digest = params_hash(params)
    inserted = await session.execute(
        insert(ActionExecution)
        .values(id=uuid7(), business_id=ctx.business_id, idempotency_key=idempotency_key,
                action=action, agent=agent, params_hash=digest)
        .on_conflict_do_nothing(index_elements=["business_id", "idempotency_key"])
        .returning(ActionExecution.id)
    )  # fmt: skip
    if inserted.scalar_one_or_none() is not None:
        return None
    prior = (
        await session.execute(
            select(ActionExecution).where(
                ActionExecution.business_id == ctx.business_id,
                ActionExecution.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one()
    # The key identifies the request, not the action the server chose for it: a retried
    # "create" may arrive after the record exists and be routed to "update".
    if prior.agent != agent or prior.params_hash != digest:
        raise IdempotencyConflictError
    if prior.result_id is None:  # the first attempt rolled back its action: cannot happen
        raise IdempotencyConflictError
    return prior.result_id


async def complete(
    session: AsyncSession, ctx: TenantContext, *, idempotency_key: str, result_id: UUID
) -> None:
    row = (
        await session.execute(
            select(ActionExecution).where(
                ActionExecution.business_id == ctx.business_id,
                ActionExecution.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one()
    row.result_id = result_id
