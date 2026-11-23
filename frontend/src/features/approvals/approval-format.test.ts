import { describe, expect, it } from "vitest";

import {
  formatTimeLeft,
  headerPairs,
  secondsUntil,
  summarizeAction,
} from "@/features/approvals/approval-format";

describe("formatTimeLeft", () => {
  it.each([
    [0, "expired"],
    [-30, "expired"],
    [1, "less than a minute"],
    [59, "less than a minute"],
    [60, "1 min"],
    [3_599, "59 min"],
    [3_600, "1 h"],
    [3_660, "1 h 1 min"],
    [86_399, "23 h 59 min"],
    [86_400, "1 d"],
    [90_000, "1 d 1 h"],
    [2 * 86_400 + 5 * 3_600, "2 d 5 h"],
  ])("%i seconds reads as %s", (seconds, expected) => {
    expect(formatTimeLeft(seconds)).toBe(expected);
  });
});

describe("secondsUntil", () => {
  const now = new Date("2026-11-22T10:00:00Z").getTime();

  it("counts whole seconds to a time, negative once it has passed", () => {
    expect(secondsUntil("2026-11-22T10:01:30Z", now)).toBe(90);
    expect(secondsUntil("2026-11-22T09:59:00Z", now)).toBe(-60);
  });

  it("treats a bad date as no time left", () => {
    expect(secondsUntil("not a date", now)).toBe(0);
  });
});

describe("summarizeAction", () => {
  it("describes a Slack message by channel and text", () => {
    expect(
      summarizeAction("slack.send_message", { channel: "C0123456789", text: "Deploy finished" }),
    ).toBe("To C0123456789: Deploy finished");
  });

  it("describes an HTTP write by method and URL", () => {
    expect(
      summarizeAction("http.request", { method: "POST", url: "https://api.example.com/x" }),
    ).toBe("POST https://api.example.com/x");
  });

  it("falls back to the data itself for other tools, shortened when long", () => {
    expect(summarizeAction("utility.calculate", { expression: "1 + 1" })).toBe(
      '{"expression":"1 + 1"}',
    );
    const long = summarizeAction("x.y", { text: "a".repeat(500) });
    expect(long.length).toBeLessThanOrEqual(161);
    expect(long.endsWith("…")).toBe(true);
  });

  it("copes with missing fields", () => {
    expect(summarizeAction("slack.send_message", {})).toBe("To : ");
    expect(summarizeAction("http.request", {})).toBe("");
  });
});

describe("headerPairs", () => {
  it("keeps well-formed pairs and drops everything else", () => {
    expect(
      headerPairs([
        { name: "Accept", value: "application/json" },
        { name: "X-Bad", value: 5 },
        { name: 5, value: "x" },
        "Accept: x",
        null,
        { name: "X-Two", value: "2" },
      ]),
    ).toEqual([
      { name: "Accept", value: "application/json" },
      { name: "X-Two", value: "2" },
    ]);
  });

  it("returns nothing when there are no headers", () => {
    expect(headerPairs(undefined)).toEqual([]);
    expect(headerPairs("x")).toEqual([]);
  });
});
