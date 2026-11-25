import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import type { RunEvent } from "@/lib/api/types";
import { followRunEvents, parseSseBuffer } from "@/lib/run-events";
import { apiStream, sseFrame, sseResponse, unavailableStream } from "@/test/api-mock";

vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const PATH = "/organizations/org-1/runs/run-1/events/stream";

describe("parseSseBuffer", () => {
  it("reads complete frames and keeps a frame that is still arriving", () => {
    const text = sseFrame(1, "run.queued") + sseFrame(2, "run.started") + "id: 3\nevent: step.sta";
    const { events, rest } = parseSseBuffer(text);
    expect(events.map((e) => e.seq)).toEqual([1, 2]);
    expect(rest).toBe("id: 3\nevent: step.sta");
  });

  it("completes a frame once the rest of it arrives", () => {
    const whole = sseFrame(4, "step.finished", { status: "succeeded" });
    const first = parseSseBuffer(whole.slice(0, 30));
    expect(first.events).toEqual([]);
    const second = parseSseBuffer(first.rest + whole.slice(30));
    expect(second.events).toEqual([
      expect.objectContaining({ seq: 4, type: "step.finished", data: { status: "succeeded" } }),
    ]);
    expect(second.rest).toBe("");
  });

  it("skips keep-alive comments, damaged frames and frames that are not events", () => {
    const text =
      ": keep-alive\n\n" +
      "id: 1\ndata: {not json\n\n" +
      'id: 2\ndata: {"hello":"world"}\n\n' +
      sseFrame(3, "run.finished");
    expect(parseSseBuffer(text).events.map((e) => e.seq)).toEqual([3]);
  });
});

function collect() {
  const events: RunEvent[] = [];
  const connection: boolean[] = [];
  return {
    events,
    connection,
    onEvent: (event: RunEvent) => events.push(event),
    onConnection: (connected: boolean) => connection.push(connected),
  };
}

const run = (options: Partial<Parameters<typeof followRunEvents>[0]> & { sleep?: never } = {}) => {
  const seen = collect();
  const sleeps: number[] = [];
  const controller = new AbortController();
  const done = followRunEvents({
    orgId: "org-1",
    runId: "run-1",
    signal: controller.signal,
    onEvent: seen.onEvent,
    onConnection: seen.onConnection,
    sleep: async (ms) => {
      sleeps.push(ms);
    },
    ...options,
  });
  return { done, seen, sleeps, controller };
};

const afterOf = (call: number) => apiStream.mock.calls[call][1].query?.after;

beforeEach(() => {
  apiStream.mockReset();
  apiStream.mockImplementation(unavailableStream);
});

describe("followRunEvents", () => {
  it("delivers events in order, even when a frame is split across chunks, and stops at the end", async () => {
    const all =
      sseFrame(1, "run.queued") + sseFrame(2, "run.started") + sseFrame(3, "run.finished");
    apiStream.mockResolvedValueOnce(
      sseResponse([all.slice(0, 40), all.slice(40, 130), all.slice(130)]),
    );
    const { done, seen } = run();
    await done;
    expect(seen.events.map((e) => e.type)).toEqual(["run.queued", "run.started", "run.finished"]);
    expect(apiStream).toHaveBeenCalledTimes(1); // a finished run is not followed any further
    expect(apiStream).toHaveBeenCalledWith(PATH, expect.objectContaining({ query: { after: 0 } }));
    expect(seen.connection).toEqual([true, false]);
  });

  it("stops when the run is cancelled", async () => {
    apiStream.mockResolvedValueOnce(
      sseResponse([sseFrame(1, "run.queued"), sseFrame(2, "run.cancelled")]),
    );
    const { done, seen } = run();
    await done;
    expect(seen.events.map((e) => e.seq)).toEqual([1, 2]);
    expect(apiStream).toHaveBeenCalledTimes(1);
  });

  it("reconnects after a normal end, asking only for what it has not seen", async () => {
    apiStream
      .mockResolvedValueOnce(sseResponse([sseFrame(1, "run.queued"), sseFrame(2, "run.started")]))
      .mockResolvedValueOnce(
        sseResponse([sseFrame(3, "step.started"), sseFrame(4, "run.finished")]),
      );
    const { done, seen, sleeps } = run();
    await done;
    expect(seen.events.map((e) => e.seq)).toEqual([1, 2, 3, 4]);
    expect(afterOf(0)).toBe(0);
    expect(afterOf(1)).toBe(2);
    expect(sleeps).toEqual([300]);
  });

  it("never delivers the same event twice if the server repeats one", async () => {
    apiStream
      .mockResolvedValueOnce(sseResponse([sseFrame(1, "run.queued"), sseFrame(2, "run.started")]))
      .mockResolvedValueOnce(
        sseResponse([sseFrame(2, "run.started"), sseFrame(3, "run.finished")]),
      );
    const { done, seen } = run();
    await done;
    expect(seen.events.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("comes back for what it missed when the connection drops part-way", async () => {
    // Delivers one frame, then fails on the next read (erroring a stream at once would discard
    // what was already queued, which is not what a dropped connection does).
    let sent = false;
    const broken = new Response(
      new ReadableStream<Uint8Array>({
        pull(controller) {
          if (sent) return controller.error(new Error("connection reset"));
          sent = true;
          controller.enqueue(new TextEncoder().encode(sseFrame(1, "run.queued")));
        },
      }),
    );
    apiStream
      .mockResolvedValueOnce(broken)
      .mockResolvedValueOnce(sseResponse([sseFrame(2, "run.finished")]));
    const { done, seen, sleeps } = run();
    await done;
    expect(seen.events.map((e) => e.seq)).toEqual([1, 2]);
    expect(afterOf(1)).toBe(1);
    expect(sleeps).toEqual([1_000]);
  });

  it("retries network failures and server errors with growing pauses", async () => {
    apiStream
      .mockRejectedValueOnce(new ApiError(0, "network_error", "offline"))
      .mockRejectedValueOnce(new ApiError(503, "queue_unavailable", "busy"))
      .mockRejectedValueOnce(new ApiError(502, "unknown_error", "bad gateway"))
      .mockResolvedValueOnce(sseResponse([sseFrame(1, "run.finished")]));
    const { done, seen, sleeps } = run();
    await done;
    expect(sleeps).toEqual([1_000, 2_000, 4_000]);
    expect(seen.events.map((e) => e.seq)).toEqual([1]);
  });

  it.each([
    ["not signed in", new ApiError(401, "not_authenticated", "Sign in")],
    ["not allowed", new ApiError(403, "forbidden", "No")],
    ["run not found", new ApiError(404, "run_not_found", "No such run")],
    ["a setup problem", new Error("Supabase is not configured")],
  ])("gives up quietly, leaving polling to cover it, when it is %s", async (_name, error) => {
    apiStream.mockRejectedValueOnce(error);
    const { done, seen, sleeps } = run();
    await expect(done).resolves.toBeUndefined();
    expect(apiStream).toHaveBeenCalledTimes(1);
    expect(sleeps).toEqual([]);
    expect(seen.events).toEqual([]);
    expect(seen.connection.at(-1)).toBe(false);
  });

  it("gives up when streaming is not available at all", async () => {
    const { done, seen } = run(); // the default response has no body
    await done;
    expect(apiStream).toHaveBeenCalledTimes(1);
    expect(seen.connection).toEqual([false]);
  });

  it("stops trying after several connections in a row that deliver nothing", async () => {
    apiStream.mockImplementation(async () => sseResponse([": keep-alive\n\n"]));
    const { done, sleeps } = run();
    await done;
    expect(apiStream).toHaveBeenCalledTimes(5);
    expect(sleeps).toHaveLength(4);
  });

  it("stops as soon as it is told to, without another request", async () => {
    const controller = new AbortController();
    apiStream.mockImplementation(async (_path, options) =>
      sseResponse([sseFrame(1, "run.queued")], { hold: options.signal }),
    );
    const { done, seen } = run({ signal: controller.signal });
    await vi.waitFor(() => expect(seen.events).toHaveLength(1));
    controller.abort();
    await done;
    expect(apiStream).toHaveBeenCalledTimes(1);
    expect(seen.connection.at(-1)).toBe(false);
  });
});
