import { describe, expect, it } from "vitest";

import {
  validateEmail,
  validateNewPassword,
  validateOrganizationName,
  validatePasswordConfirmation,
  validateSlug,
} from "@/lib/validation";

describe("validateEmail", () => {
  it.each(["a@b.co", "first.last+tag@example.com", " padded@example.com "])("accepts %s", (v) => {
    expect(validateEmail(v)).toBeNull();
  });
  it.each(["", "   ", "plain", "a@b", "a@@b.com", "a b@c.com", "@c.com"])("rejects %j", (v) => {
    expect(validateEmail(v)).toBeTruthy();
  });
});

describe("validateNewPassword", () => {
  it("requires a value and a minimum length", () => {
    expect(validateNewPassword("")).toBe("Choose a password.");
    expect(validateNewPassword("short")).toMatch(/at least 8/);
    expect(validateNewPassword("long-enough")).toBeNull();
  });
});

describe("validatePasswordConfirmation", () => {
  it("must be present and equal", () => {
    expect(validatePasswordConfirmation("abc12345", "")).toBeTruthy();
    expect(validatePasswordConfirmation("abc12345", "abc12346")).toMatch(/do not match/);
    expect(validatePasswordConfirmation("abc12345", "abc12345")).toBeNull();
  });
});

describe("validateOrganizationName", () => {
  it("trims and bounds the length", () => {
    expect(validateOrganizationName(" a ")).toBeTruthy();
    expect(validateOrganizationName("Ac")).toBeNull();
    expect(validateOrganizationName("x".repeat(101))).toBeTruthy();
  });
});

describe("validateSlug", () => {
  it("allows empty, and the same shape the API enforces", () => {
    expect(validateSlug("")).toBeNull();
    expect(validateSlug("acme-1")).toBeNull();
    for (const bad of ["a", "-acme", "Acme", "has space", "under_score", "x".repeat(64)]) {
      expect(validateSlug(bad), bad).toBeTruthy();
    }
  });
});
