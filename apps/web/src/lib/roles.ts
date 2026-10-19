import type { Role } from "./api";

/**
 * Mirror of the backend role rules, used ONLY to hide controls a user cannot use.
 * The backend enforces every rule; a hidden button is a convenience, not a control.
 */
const RANK: Record<Role, number> = { member: 1, admin: 2, owner: 3 };

export const ROLES: Role[] = ["owner", "admin", "member"];

export const ROLE_LABEL: Record<Role, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
};

export const atLeast = (role: Role, minimum: Role) => RANK[role] >= RANK[minimum];

/** Roles the actor may grant (up to their own rank, admin+ only). */
export const grantableRoles = (actor: Role): Role[] =>
  atLeast(actor, "admin") ? ROLES.filter((r) => RANK[r] <= RANK[actor]) : [];

/** Owners manage anyone; admins manage members only. */
export const canManage = (actor: Role, target: Role) =>
  actor === "owner" || (actor === "admin" && target === "member");
