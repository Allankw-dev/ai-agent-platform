import { vi } from "vitest";

import { ApiError } from "@/lib/api-client";

type Call = { method: string; path: string; body?: unknown; query?: Record<string, unknown> };
type Handler = (call: Call) => unknown;

export const apiFetch = vi.fn();

/**
 * Live streams (server-sent events). By default a stream is "not available" (a response with no
 * body), so pages fall back to polling exactly as they do when a browser cannot stream. A test
 * that wants a live stream replaces the implementation (see `sseResponse`).
 */
export const unavailableStream = async () => new Response(null, { status: 200 });
type StreamOptions = { query?: Record<string, string | number | undefined>; signal: AbortSignal };
export const apiStream =
  vi.fn<(path: string, options: StreamOptions) => Promise<Response>>(unavailableStream);

/** A streamed response whose body arrives in the given chunks, then ends (unless `hold` is set). */
export function sseResponse(chunks: string[], options: { hold?: AbortSignal } = {}): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!options.hold) controller.close();
      else options.hold.addEventListener("abort", () => controller.error(new Error("aborted")));
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

/** A stream the test feeds by hand: `send` pushes text to the page, `end` closes the connection. */
export function liveStream(signal?: AbortSignal) {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  signal?.addEventListener("abort", () => {
    try {
      controller.error(new Error("aborted"));
    } catch {
      // already closed
    }
  });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
  };
}

/** One server-sent-event frame, formatted as the API sends it. */
export function sseFrame(seq: number, type: string, data: Record<string, unknown> = {}): string {
  const event = { seq, type, data, created_at: "2026-11-24T10:00:00Z" };
  return `id: ${seq}\nevent: ${type}\ndata: ${JSON.stringify(event)}\n\n`;
}

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
  return { ...(await importOriginal()), apiFetch, apiStream };
}
