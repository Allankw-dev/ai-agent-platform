import { describe, expect, it } from "vitest";

import { safeNext } from "@/lib/safe-redirect";

describe("safeNext", () => {
  it.each(["/dashboard", "/orgs/123/members", "/invite/abc?x=1#y", "/"])("keeps %s", (v) => {
    expect(safeNext(v)).toBe(v);
  });

  it.each([
    null,
    undefined,
    "",
    "dashboard",
    "//evil.example.com",
    "https://evil.example.com",
    "http://localhost:3000/dashboard",
    "/\\evil.example.com",
    "\\\\evil.example.com",
    "javascript:alert(1)",
    "/ok\nSet-Cookie: x=1",
  ])("rejects %j", (v) => {
    expect(safeNext(v)).toBeNull();
  });
});
