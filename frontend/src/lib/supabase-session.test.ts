import { createClient } from "@supabase/supabase-js";
import { describe, expect, it, vi } from "vitest";

import { passwordGrantResponse, signUpNeedsConfirmationResponse } from "../../e2e/fixtures";

/**
 * Runs the REAL supabase-js client against a faked server. It proves the sign-in payload used by
 * the Playwright tests is one the library accepts, so those tests do not rest on guesses.
 */
describe("supabase-js with the Playwright fixtures", () => {
  it("accepts the password-grant response and exposes the access token", async () => {
    const fetchMock = vi.fn<(input: unknown) => Promise<Response>>(
      async () =>
        new Response(JSON.stringify(passwordGrantResponse("ada@example.com")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const supabase = createClient("http://localhost:54321", "sb_publishable_dummy", {
      auth: { persistSession: false, autoRefreshToken: false },
      global: { fetch: fetchMock as unknown as typeof fetch },
    });

    const { data, error } = await supabase.auth.signInWithPassword({
      email: "ada@example.com",
      password: "pw",
    });
    expect(error).toBeNull();
    expect(data.session?.user.email).toBe("ada@example.com");

    const { data: stored } = await supabase.auth.getSession();
    expect(stored.session?.access_token.split(".")).toHaveLength(3);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/auth/v1/token?grant_type=password");
  });

  it("accepts the sign-up response used when email confirmation is required", async () => {
    const fetchMock = vi.fn<(input: unknown) => Promise<Response>>(
      async () =>
        new Response(JSON.stringify(signUpNeedsConfirmationResponse("new@example.com")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    );
    const supabase = createClient("http://localhost:54321", "sb_publishable_dummy", {
      auth: { persistSession: false, autoRefreshToken: false },
      global: { fetch: fetchMock as unknown as typeof fetch },
    });

    const { data, error } = await supabase.auth.signUp({
      email: "new@example.com",
      password: "long-enough-1",
    });
    expect(error).toBeNull();
    expect(data.session).toBeNull();
    expect(data.user?.email).toBe("new@example.com");
  });
});
