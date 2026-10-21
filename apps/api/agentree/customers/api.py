"""Customers and their memory (Task 16): members read; Owners and Admins correct and delete."""

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from agentree.customers import service
from agentree.customers.schemas import (
    CustomerDetailOut,
    CustomerOut,
    MemoryItemIn,
    MemoryItemOut,
)
from agentree.tenancy.deps import Member
from agentree.tenancy.roles import Role

router = APIRouter(prefix="/api/businesses/{business_id}/customers", tags=["customers"])


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "not_found")


@router.get("")
async def list_customers(member: Member, request: Request) -> list[CustomerOut]:
    rows = await service.list_customers(request.app.state.session_factory, member.tenant)
    return [CustomerOut(**asdict(c)) for c in rows]


@router.get("/{customer_id}")
async def get_customer(customer_id: UUID, member: Member, request: Request) -> CustomerDetailOut:
    try:
        info, items = await service.get_customer(
            request.app.state.session_factory, member.tenant, customer_id
        )
    except service.NotFoundError:
        raise _not_found() from None
    return CustomerDetailOut(customer=CustomerOut(**asdict(info)),
                             memory=[MemoryItemOut(**asdict(i)) for i in items])  # fmt: skip


@router.patch("/{customer_id}/memory/{item_id}")
async def update_memory_item(
    customer_id: UUID, item_id: UUID, body: MemoryItemIn, member: Member, request: Request
) -> MemoryItemOut:
    member.require(Role.ADMIN)
    try:
        item = await service.update_item(
            request.app.state.session_factory, member.tenant, customer_id, item_id,
            value=body.value, actor_id=member.user.id,
        )  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None
    except service.InvalidMemoryError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_memory") from None
    return MemoryItemOut(**asdict(item))


@router.delete("/{customer_id}/memory/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_item(
    customer_id: UUID, item_id: UUID, member: Member, request: Request
) -> None:
    member.require(Role.ADMIN)
    try:
        await service.delete_item(request.app.state.session_factory, member.tenant, customer_id,
                                  item_id, actor_id=member.user.id)  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: UUID, member: Member, request: Request) -> None:
    member.require(Role.ADMIN)
    try:
        await service.delete_customer(request.app.state.session_factory, member.tenant,
                                      customer_id, actor_id=member.user.id)  # fmt: skip
    except service.NotFoundError:
        raise _not_found() from None
