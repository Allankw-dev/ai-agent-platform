import { describe, expect, it } from "vitest";

import {
  canAssign,
  canDeleteOrganization,
  canManage,
  canManageAgents,
  canManageMembers,
  canUpdateOrganization,
  invitableRoles,
} from "@/lib/permissions";

// These tables mirror backend/tests/test_permissions.py. If one changes, change both.
describe("role rules (mirror of the API)", () => {
  it("organization-level permissions", () => {
    expect(canDeleteOrganization("owner")).toBe(true);
    for (const role of ["admin", "developer", "member"] as const) {
      expect(canDeleteOrganization(role)).toBe(false);
    }
    expect(["owner", "admin"].every((r) => canUpdateOrganization(r as never))).toBe(true);
    expect(["developer", "member"].some((r) => canUpdateOrganization(r as never))).toBe(false);
    expect(["owner", "admin"].every((r) => canManageMembers(r as never))).toBe(true);
    expect(["developer", "member"].some((r) => canManageMembers(r as never))).toBe(false);
  });

  it.each([
    ["owner", "owner", true],
    ["owner", "member", true],
    ["admin", "owner", false],
    ["admin", "admin", false],
    ["admin", "developer", true],
    ["admin", "member", true],
    ["developer", "member", true],
    ["member", "member", false],
    ["member", "developer", false],
  ] as const)("canManage(%s, %s) = %s", (actor, target, expected) => {
    expect(canManage(actor, target)).toBe(expected);
  });

  it.each([
    ["owner", "owner", true],
    ["owner", "admin", true],
    ["admin", "owner", false],
    ["admin", "admin", false],
    ["admin", "developer", true],
    ["admin", "member", true],
    ["developer", "member", true],
    ["developer", "developer", false],
  ] as const)("canAssign(%s, %s) = %s", (actor, role, expected) => {
    expect(canAssign(actor, role)).toBe(expected);
  });

  it("invitations never offer owner and never exceed the inviter's level", () => {
    expect(invitableRoles("owner")).toEqual(["admin", "developer", "member"]);
    expect(invitableRoles("admin")).toEqual(["developer", "member"]);
    expect(invitableRoles("member")).toEqual([]);
  });
});

describe("agent permissions (mirror of the API)", () => {
  it("owners, admins and developers manage agents; members only view them", () => {
    for (const role of ["owner", "admin", "developer"] as const) {
      expect(canManageAgents(role)).toBe(true);
    }
    expect(canManageAgents("member")).toBe(false);
  });
});
