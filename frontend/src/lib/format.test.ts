import { describe, expect, it, vi } from "vitest";

import { formatCost, formatDateTime, formatDuration, newIdempotencyKey } from "@/lib/format";

describe("formatDuration", () => {
  const at = (seconds: number) =>
    new Date(Date.UTC(2026, 10, 13, 9, 0, 0) + seconds * 1000).toISOString();
  const start = at(0);

  it.each([
    [0.25, "250 ms"],
    [3, "3.0 s"],
    [12.34, "12.3 s"],
    [59.9, "59.9 s"],
    [125, "2 min 5 s"],
  ])("%s seconds reads as %s", (seconds, text) => {
    expect(formatDuration(start, at(seconds))).toBe(text);
  });

  it("is empty until the run has both started and finished", () => {
    expect(formatDuration(null, at(1))).toBe("");
    expect(formatDuration(start, null)).toBe("");
  });

  it("is empty for nonsense or backwards times", () => {
    expect(formatDuration("not a date", at(1))).toBe("");
    expect(formatDuration(at(5), at(1))).toBe("");
  });
});

describe("formatCost", () => {
  it("shows real estimates with enough precision for tiny amounts", () => {
    expect(formatCost(0.007, 1_000)).toBe("$0.0070");
    expect(formatCost(0.0004, 10)).toBe("$0.0004");
    expect(formatCost(1.5, 1_000)).toBe("$1.50");
  });

  it("never shows a misleading $0 when tokens were used but no price is configured", () => {
    expect(formatCost(0, 850)).toBe("Not estimated");
  });

  it("shows a dash when nothing was used", () => {
    expect(formatCost(0, 0)).toBe("–");
  });
});

describe("formatDateTime", () => {
  it("formats a valid timestamp and is empty for a bad one", () => {
    expect(formatDateTime("2026-11-13T09:00:00Z")).toMatch(/Nov 13, 2026/);
    expect(formatDateTime("nope")).toBe("");
  });
});

describe("newIdempotencyKey", () => {
  it("returns a different, non-empty key each time", () => {
    const keys = new Set(Array.from({ length: 50 }, () => newIdempotencyKey()));
    expect(keys.size).toBe(50);
    expect([...keys].every((key) => key.length >= 8)).toBe(true);
  });

  it("still works where crypto.randomUUID is missing", () => {
    vi.stubGlobal("crypto", {});
    try {
      expect(newIdempotencyKey().length).toBeGreaterThanOrEqual(8);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
