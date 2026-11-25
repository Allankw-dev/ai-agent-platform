import { ApiError, apiStream } from "@/lib/api-client";
import type { RunEvent } from "@/lib/api/types";

/** The events after which a run has nothing more to tell. */
const LAST_EVENTS: RunEvent["type"][] = ["run.finished", "run.cancelled"];

/**
 * Splits received text into complete server-sent-event frames. Text after the last blank line is
 * a frame still arriving: it is handed back as `rest` to be completed by the next chunk. Comment
 * lines (keep-alives) and frames that are not valid events are skipped.
 */
export function parseSseBuffer(buffer: string): { events: RunEvent[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: RunEvent[] = [];
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) continue;
    try {
      const event = JSON.parse(data) as Partial<RunEvent>;
      if (typeof event.seq === "number" && typeof event.type === "string") {
        events.push(event as RunEvent);
      }
    } catch {
      // A damaged frame is skipped; polling still keeps the page right.
    }
  }
  return { events, rest };
}

export type FollowOptions = {
  orgId: string;
  runId: string;
  signal: AbortSignal;
  /** Called once for each event, in order, never twice for the same sequence number. */
  onEvent: (event: RunEvent) => void;
  /** True while the live connection is open; false whenever it is not. */
  onConnection: (connected: boolean) => void;
  /** Waits before reconnecting. Replaceable so tests need no real waiting. */
  sleep?: (ms: number) => Promise<void>;
};

const RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 15_000];
const RECONNECT_DELAY_MS = 300;
/** After this many connections in a row that delivered nothing, stop trying: polling covers it. */
const MAX_EMPTY_CONNECTIONS = 5;

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done);
  });
}

/**
 * Follows a run's live events until it ends, the caller aborts, or live updates are not possible.
 *
 * Connections end for ordinary reasons (the server closes each one after a few minutes, and
 * networks drop), so it reconnects asking only for events after the last sequence number it saw.
 * Server errors and network failures are retried with growing pauses; anything else (signed out,
 * run not found) stops quietly. It never throws: the page's regular polling is the safety net.
 */
export async function followRunEvents(options: FollowOptions): Promise<void> {
  const { orgId, runId, signal, onEvent, onConnection } = options;
  const sleep = options.sleep ?? ((ms: number) => wait(ms, signal));
  const backoff = (failures: number) =>
    RETRY_DELAYS_MS[Math.min(failures, RETRY_DELAYS_MS.length - 1)];
  let after = 0;
  let failures = 0;
  let emptyConnections = 0;

  while (!signal.aborted) {
    let response: Response;
    try {
      response = await apiStream(`/organizations/${orgId}/runs/${runId}/events/stream`, {
        query: { after },
        signal,
      });
    } catch (error) {
      if (signal.aborted) break;
      const retryable = error instanceof ApiError && (error.status === 0 || error.status >= 500);
      if (!retryable) break; // signed out, run not found, stream not available: polling covers it
      onConnection(false);
      await sleep(backoff(failures));
      failures += 1;
      continue;
    }
    if (!response.body) break; // streaming is not available here

    let received = 0;
    onConnection(true);
    try {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        const parsed = parseSseBuffer(buffer);
        buffer = parsed.rest;
        for (const event of parsed.events) {
          if (event.seq <= after) continue;
          after = event.seq;
          received += 1;
          onEvent(event);
          if (LAST_EVENTS.includes(event.type)) {
            onConnection(false);
            return;
          }
        }
      }
    } catch {
      // The connection dropped part-way (or the caller aborted). Come back for what was missed.
      if (signal.aborted) break;
      onConnection(false);
      failures = received > 0 ? 0 : failures + 1;
      await sleep(backoff(failures));
      continue;
    }

    // The server ended this connection normally (it does so after a few minutes).
    onConnection(false);
    failures = 0;
    emptyConnections = received > 0 ? 0 : emptyConnections + 1;
    if (emptyConnections >= MAX_EMPTY_CONNECTIONS) break;
    await sleep(RECONNECT_DELAY_MS);
  }
  onConnection(false);
}
