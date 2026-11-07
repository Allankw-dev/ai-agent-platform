import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiUnreachableError, getReadiness } from "@/lib/api";

function mockFetch(response: Response | Error) {
  const fn = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getReadiness", () => {
  it("returns the readiness payload on 200", async () => {
    const fetchMock = mockFetch(json({ status: "ready", checks: { database: true, redis: true } }));
    await expect(getReadiness()).resolves.toEqual({
      status: "ready",
      checks: { database: true, redis: true },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/health/ready",
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("treats 503 as a valid answer with a failing dependency", async () => {
    mockFetch(json({ status: "unavailable", checks: { database: true, redis: false } }, 503));
    const result = await getReadiness();
    expect(result.status).toBe("unavailable");
    expect(result.checks.redis).toBe(false);
  });

  it("throws ApiUnreachableError when the network request fails", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    await expect(getReadiness()).rejects.toBeInstanceOf(ApiUnreachableError);
  });

  it("throws on unexpected HTTP statuses", async () => {
    mockFetch(json({ detail: "boom" }, 500));
    await expect(getReadiness()).rejects.toThrow("HTTP 500");
  });

  it("throws when the body has an unexpected shape", async () => {
    mockFetch(json({ hello: "world" }));
    await expect(getReadiness()).rejects.toThrow("unexpected response format");
  });
});
