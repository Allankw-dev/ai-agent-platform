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
