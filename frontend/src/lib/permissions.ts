import type { OrgRole } from "@/lib/api/types";

/**
 * Mirrors the API's rules so the interface only offers actions that can succeed. This is a
 * convenience, not security: the API enforces every rule and is the source of truth.
 */
export const ROLES: OrgRole[] = ["owner", "admin", "developer", "member"];

const RANK: Record<OrgRole, number> = { owner: 4, admin: 3, developer: 2, member: 1 };

export const ROLE_LABELS: Record<OrgRole, string> = {
  owner: "Owner",
  admin: "Admin",
  developer: "Developer",
  member: "Member",
};

export const canUpdateOrganization = (role: OrgRole) => role === "owner" || role === "admin";
export const canDeleteOrganization = (role: OrgRole) => role === "owner";
export const canManageMembers = (role: OrgRole) => role === "owner" || role === "admin";

/** May `actor` change or remove someone currently holding `target`? */
export const canManage = (actor: OrgRole, target: OrgRole) =>
  actor === "owner" || RANK[actor] > RANK[target];

/** May `actor` hand out `newRole`? */
export const canAssign = (actor: OrgRole, newRole: OrgRole) =>
  actor === "owner" || RANK[newRole] < RANK[actor];

/** Roles an invitation can carry: never owner. */
export const invitableRoles = (actor: OrgRole): OrgRole[] =>
  ROLES.filter((role) => role !== "owner" && canAssign(actor, role));

/** Create, edit, version, roll back, duplicate, enable/disable and delete agents. */
export const canManageAgents = (role: OrgRole) =>
  role === "owner" || role === "admin" || role === "developer";
