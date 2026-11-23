import type { ApprovalStatus } from "@/lib/api/types";

/** "less than a minute", "42 min", "5 h 12 min", "1 d 2 h". Zero or less reads as "expired". */
export function formatTimeLeft(seconds: number): string {
  if (seconds <= 0) return "expired";
  if (seconds < 60) return "less than a minute";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  if (hours < 24) return restMinutes ? `${hours} h ${restMinutes} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `${days} d ${restHours} h` : `${days} d`;
}

/** Whole seconds from `now` until an ISO time (negative once it has passed). */
export function secondsUntil(iso: string, now: number = Date.now()): number {
  const then = new Date(iso).getTime();
  return Number.isNaN(then) ? 0 : Math.floor((then - now) / 1_000);
}

export const STATUS_LABELS: Record<ApprovalStatus, string> = {
  pending: "Waiting for a decision",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
  cancelled: "Cancelled",
};

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** One line saying what an approval is about, for the inbox. */
export function summarizeAction(toolKey: string, input: Record<string, unknown>): string {
  if (toolKey === "slack.send_message") {
    return `To ${text(input.channel)}: ${text(input.text)}`;
  }
  if (toolKey === "http.request") {
    return `${text(input.method)} ${text(input.url)}`.trim();
  }
  const compact = JSON.stringify(input);
  return compact.length > 160 ? `${compact.slice(0, 160)}…` : compact;
}

export type HeaderPair = { name: string; value: string };

/** The `headers` argument of an HTTP call as clean pairs (anything malformed is left out). */
export function headerPairs(value: unknown): HeaderPair[] {
  if (!Array.isArray(value)) return [];
  const pairs: HeaderPair[] = [];
  for (const item of value) {
    if (item && typeof item === "object") {
      const { name, value: headerValue } = item as Record<string, unknown>;
      if (typeof name === "string" && typeof headerValue === "string") {
        pairs.push({ name, value: headerValue });
      }
    }
  }
  return pairs;
}
