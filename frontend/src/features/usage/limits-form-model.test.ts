import { describe, expect, it } from "vitest";

import {
  sameLimits,
  toLimitsInput,
  validateLimits,
  valuesFromLimits,
  type LimitsFormValues,
} from "@/features/usage/limits-form-model";

const valid = (overrides: Partial<LimitsFormValues> = {}): LimitsFormValues => ({
  maxConcurrentRuns: "5",
  dailyTokenQuota: "500000",
  dailyCostQuota: "",
  ...overrides,
});

describe("validateLimits", () => {
  it("accepts the platform defaults and a cost quota", () => {
    expect(validateLimits(valid())).toEqual({});
    expect(validateLimits(valid({ dailyCostQuota: "12.5" }))).toEqual({});
    expect(validateLimits(valid({ dailyCostQuota: "0.000001" }))).toEqual({});
  });

  it.each([
    ["maxConcurrentRuns", "0"],
    ["maxConcurrentRuns", "1001"],
    ["maxConcurrentRuns", "five"],
    ["maxConcurrentRuns", "2.5"],
    ["maxConcurrentRuns", ""],
    ["dailyTokenQuota", "999"],
    ["dailyTokenQuota", "2000000001"],
    ["dailyTokenQuota", "lots"],
    ["dailyTokenQuota", "-5"],
    ["dailyCostQuota", "0"],
    ["dailyCostQuota", "-1"],
    ["dailyCostQuota", "abc"],
    ["dailyCostQuota", "1.1234567"],
    ["dailyCostQuota", "1000001"],
  ] as const)("rejects %s = %j", (field, value) => {
    expect(validateLimits(valid({ [field]: value }))[field]).toBeTruthy();
  });

  it("accepts thousands separators and spaces in whole numbers", () => {
    expect(validateLimits(valid({ dailyTokenQuota: " 1,500,000 " }))).toEqual({});
  });

  it("explains the allowed range", () => {
    expect(validateLimits(valid({ maxConcurrentRuns: "0" })).maxConcurrentRuns).toBe(
      "Use 1 to 1,000 runs.",
    );
  });
});

describe("toLimitsInput", () => {
  it("turns the text into the API's numbers, with no cost quota as null", () => {
    expect(toLimitsInput(valid({ dailyTokenQuota: " 1,500,000 " }))).toEqual({
      max_concurrent_runs: 5,
      daily_token_quota: 1_500_000,
      daily_cost_quota_usd: null,
    });
    expect(toLimitsInput(valid({ dailyCostQuota: " 2.5 " })).daily_cost_quota_usd).toBe(2.5);
  });
});

describe("valuesFromLimits and sameLimits", () => {
  const limits = {
    max_concurrent_runs: 3,
    daily_token_quota: 250_000,
    daily_cost_quota_usd: 2.5,
    customized: true,
    updated_at: "2026-11-25T10:00:00Z",
  };

  it("fills the form from the saved limits, and an empty cost quota when there is none", () => {
    expect(valuesFromLimits(limits)).toEqual({
      maxConcurrentRuns: "3",
      dailyTokenQuota: "250000",
      dailyCostQuota: "2.5",
    });
    expect(valuesFromLimits({ ...limits, daily_cost_quota_usd: null }).dailyCostQuota).toBe("");
  });

  it("does not see formatting as a change", () => {
    const saved = valuesFromLimits(limits);
    expect(sameLimits(saved, { ...saved, dailyTokenQuota: " 250,000 " })).toBe(true);
    expect(sameLimits(saved, { ...saved, maxConcurrentRuns: "4" })).toBe(false);
    expect(sameLimits(saved, { ...saved, dailyCostQuota: "" })).toBe(false);
  });
});
