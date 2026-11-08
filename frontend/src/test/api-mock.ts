import { vi } from "vitest";

import { ApiError } from "@/lib/api-client";

type Call = { method: string; path: string; body?: unknown; query?: Record<string, unknown> };
type Handler = (call: Call) => unknown;

export const apiFetch = vi.fn();

/** Maps "METHOD /path" to a handler (or a value). Unmatched calls fail loudly. */
export function routeApi(routes: Record<string, Handler | unknown>) {
  apiFetch.mockImplementation(
    async (
      path: string,
      options: { method?: string; body?: unknown; query?: Record<string, unknown> } = {},
    ) => {
      const method = options.method ?? "GET";
      const key = `${method} ${path}`;
      if (!(key in routes)) throw new Error(`Unexpected API call: ${key}`);
      const route = routes[key];
      const result =
        typeof route === "function" ? (route as Handler)({ method, path, ...options }) : route;
      if (result instanceof Error) throw result;
      return result;
    },
  );
}

export const apiError = (status: number, code: string, message: string) =>
  new ApiError(status, code, message);

export function callsTo(method: string, path: string) {
  return apiFetch.mock.calls.filter(
    ([p, o]) => p === path && ((o as { method?: string } | undefined)?.method ?? "GET") === method,
  );
}

export async function apiClientFactory(importOriginal: () => Promise<Record<string, unknown>>) {
  return { ...(await importOriginal()), apiFetch };
}
