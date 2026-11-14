import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api-client";
import * as supabase from "@/lib/supabase";

vi.mock("@/lib/supabase", async (importOriginal) =>
  (await import("@/test/supabase-mock")).supabaseFactory(importOriginal),
);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.mocked(supabase.getAccessToken).mockResolvedValue("test-token");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("sends the bearer token and returns parsed JSON", async () => {
    fetchMock.mockResolvedValue(json({ ok: true }));
    await expect(apiFetch("/organizations")).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/api/v1/organizations");
    expect(init.method).toBe("GET");
    expect(init.headers.Authorization).toBe("Bearer test-token");
    expect(init.headers["Content-Type"]).toBeUndefined();
  });

  it("sends JSON bodies with a content type", async () => {
    fetchMock.mockResolvedValue(json({ id: "1" }, 201));
    await apiFetch("/organizations", { method: "POST", body: { name: "Acme" } });
    const init = fetchMock.mock.calls[0][1];
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"name":"Acme"}');
  });

  it("sends extra headers but never lets them replace the bearer token", async () => {
    fetchMock.mockResolvedValue(json({}));
    await apiFetch("/x", {
      method: "POST",
      body: {},
      headers: { "Idempotency-Key": "abc-123", Authorization: "Bearer attacker" },
    });
    const init = fetchMock.mock.calls[0][1];
    expect(init.headers["Idempotency-Key"]).toBe("abc-123");
    expect(init.headers.Authorization).toBe("Bearer test-token");
  });

  it("builds a query string and skips undefined values", async () => {
    fetchMock.mockResolvedValue(json({}));
    await apiFetch("/x", { query: { limit: 10, offset: undefined } });
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/x?limit=10");
  });

  it("returns undefined for 204 responses", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch("/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("turns the API's structured error into an ApiError", async () => {
    fetchMock.mockResolvedValue(
      json({ error: { code: "last_owner", message: "Keep one owner." } }, 409),
    );
    const error = await apiFetch("/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, code: "last_owner", message: "Keep one owner." });
  });

  it("falls back to a generic message when the error body is unusable", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502 }));
    const error = await apiFetch("/x").catch((e: unknown) => e);
    expect(error).toMatchObject({ status: 502, code: "unknown_error" });
    expect((error as Error).message).not.toContain("html");
  });

  it("reports an unreachable server as a network_error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("does not call the server without a signed-in user", async () => {
    vi.mocked(supabase.getAccessToken).mockResolvedValue(null);
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 401, code: "not_authenticated" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
