import { describe, expect, it } from "vitest";

import { describeAuthError } from "@/lib/auth-errors";
import { SupabaseNotConfiguredError } from "@/lib/supabase";

describe("describeAuthError", () => {
  it.each([
    [{ message: "Invalid login credentials", status: 400 }, /Incorrect email or password/],
    [{ message: "Email not confirmed", status: 400 }, /Confirm your email/],
    [{ message: "x", status: 429 }, /Too many attempts/],
    [{ message: "email rate limit exceeded" }, /Too many attempts/],
    [{ message: "Failed to fetch" }, /Could not reach/],
    [{ message: "New password should be different from the old password." }, /not used before/],
    [{ message: "Password is known to be weak" }, /too easy to guess/],
    [{ message: "something odd" }, /Something went wrong/],
    [null, /Something went wrong/],
  ])("maps %j", (error, expected) => {
    expect(describeAuthError(error)).toMatch(expected);
  });

  it("explains a missing configuration", () => {
    expect(describeAuthError(new SupabaseNotConfiguredError())).toMatch(/not configured/);
  });

  it("never echoes raw provider text for unknown errors", () => {
    expect(describeAuthError({ message: "internal stack trace at line 42" })).not.toMatch(/stack/);
  });
});
