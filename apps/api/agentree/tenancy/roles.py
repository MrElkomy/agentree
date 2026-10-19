"""Basic roles and the permission rules for member management (code-defined, no role builder)."""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


RANK = {Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


def at_least(role: Role, minimum: Role) -> bool:
    return RANK[role] >= RANK[minimum]


def can_grant(actor: Role, target_role: Role) -> bool:
    """Admins+ may grant roles up to their own rank."""
    return at_least(actor, Role.ADMIN) and RANK[target_role] <= RANK[actor]


def can_manage(actor: Role, target_current: Role) -> bool:
    """Owners manage anyone; admins manage members only."""
    if actor is Role.OWNER:
        return True
    return actor is Role.ADMIN and target_current is Role.MEMBER
