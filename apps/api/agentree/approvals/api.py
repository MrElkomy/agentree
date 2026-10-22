"""Approvals (Task 19). Members see requests; only Owners and Admins decide and manage
"always allow" rules. The decision runs the action right away (the worker is a safety net)."""

from dataclasses import asdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from agentree.approvals import service
from agentree.approvals.schemas import ApprovalOut, DecisionIn, RuleOut
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}", tags=["approvals"])


def _deps(request: Request) -> service.Deps:
    s = request.app.state
    return service.Deps(s.settings, s.mailer, s.push)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


@router.get("/approvals")
async def list_approvals(
    member: Member, request: Request,
    view: Literal["pending", "history"] = "pending", limit: int = Query(50, ge=1, le=100),
) -> list[ApprovalOut]:  # fmt: skip
    rows = await service.list_requests(request.app.state.session_factory, member.tenant,
                                       pending=view == "pending", limit=limit)  # fmt: skip
    return [ApprovalOut(**asdict(r)) for r in rows]


@router.get("/approvals/{approval_id}")
async def get_approval(approval_id: UUID, member: Member, request: Request) -> ApprovalOut:
    try:
        r = await service.get_request(request.app.state.session_factory, member.tenant,
                                      approval_id)  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None
    return ApprovalOut(**asdict(r))


@router.post("/approvals/{approval_id}/decision")
async def decide(
    approval_id: UUID, body: DecisionIn, member: Member, request: Request, tasks: BackgroundTasks
) -> ApprovalOut:
    """Approve once, approve and always allow, or reject. 409 `not_pending`, `expired`,
    `always_not_allowed`; 422 with the field name when an edit is invalid."""
    member.require(Role.ADMIN)
    factory = request.app.state.session_factory
    try:
        r = await service.decide(factory, member.tenant, approval_id, actor_id=member.user.id,
                                 decision=body.decision, edits=body.edits)  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None
    except service.InvalidStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except service.InvalidEditError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if r.status == "approved":
        tasks.add_task(service.execute, factory, member.tenant, _deps(request), r.id)
    return ApprovalOut(**asdict(r))


@router.get("/approval-rules")
async def list_rules(member: Member, request: Request) -> list[RuleOut]:
    rules = await service.list_rules(request.app.state.session_factory, member.tenant)
    return [RuleOut(**asdict(r)) for r in rules]


@router.delete("/approval-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: UUID, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await service.delete_rule(request.app.state.session_factory, member.tenant, rule_id,
                                  actor_id=member.user.id)  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None
