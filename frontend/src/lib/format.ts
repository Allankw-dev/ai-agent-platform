const DATE_TIME = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" });

/** "Nov 12, 2026, 9:05 AM" in the viewer's time zone. Returns "" for an unparsable value. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : DATE_TIME.format(date);
}

/** "0.4 s", "12.3 s", "2 min 5 s". Returns "" when the run has not both started and finished. */
export function formatDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return "";
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1_000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1_000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}

/**
 * The estimated cost of a run. A cost of 0 with tokens used means the server has no price for the
 * model, so it says "Not estimated" rather than showing a misleading $0.
 */
export function formatCost(costUsd: number, totalTokens: number): string {
  if (costUsd > 0) return costUsd < 0.01 ? `$${costUsd.toFixed(4)}` : `$${costUsd.toFixed(2)}`;
  return totalTokens > 0 ? "Not estimated" : "–";
}

/** A fresh id for an `Idempotency-Key` header. */
export function newIdempotencyKey(): string {
  const crypto = globalThis.crypto;
  if (crypto && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** How long ago something happened, in seconds (0 for an unparsable time). */
export function secondsSince(iso: string, now: number = Date.now()): number {
  const then = new Date(iso).getTime();
  return Number.isNaN(then) ? 0 : Math.max(0, Math.floor((now - then) / 1_000));
}

/** "over a minute", "5 minutes", "2 hours": a rough wait, for messages to people. */
export function formatWait(seconds: number): string {
  if (seconds < 120) return "over a minute";
  if (seconds < 3_600) return `${Math.floor(seconds / 60)} minutes`;
  const hours = Math.floor(seconds / 3_600);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}
