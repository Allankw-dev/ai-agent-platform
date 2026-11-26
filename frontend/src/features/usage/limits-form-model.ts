import type { OrgLimits, OrgLimitsInput } from "@/lib/api/types";

/** The ranges the API accepts (it explains any refusal itself). */
export const LIMIT_RANGES = {
  maxConcurrentRuns: { min: 1, max: 1_000 },
  dailyTokenQuota: { min: 1_000, max: 2_000_000_000 },
  dailyCostQuotaUsd: { max: 1_000_000 },
} as const;

export type LimitsFormValues = {
  maxConcurrentRuns: string;
  dailyTokenQuota: string;
  /** Empty means no daily cost quota. */
  dailyCostQuota: string;
};

export type LimitsFormErrors = Partial<Record<keyof LimitsFormValues, string>>;

const WHOLE = /^\d+$/;
const DECIMAL = /^\d{1,7}(\.\d{1,6})?$/;

export function valuesFromLimits(limits: OrgLimits): LimitsFormValues {
  return {
    maxConcurrentRuns: String(limits.max_concurrent_runs),
    dailyTokenQuota: String(limits.daily_token_quota),
    dailyCostQuota: limits.daily_cost_quota_usd == null ? "" : String(limits.daily_cost_quota_usd),
  };
}

function checkWhole(text: string, range: { min: number; max: number }, unit: string) {
  const value = text.trim().replace(/,/g, "");
  if (!WHOLE.test(value)) return `Enter a whole number of ${unit}.`;
  const number = Number(value);
  if (number < range.min || number > range.max) {
    return `Use ${range.min.toLocaleString("en")} to ${range.max.toLocaleString("en")} ${unit}.`;
  }
  return null;
}

export function validateLimits(values: LimitsFormValues): LimitsFormErrors {
  const errors: LimitsFormErrors = {};
  const runs = checkWhole(values.maxConcurrentRuns, LIMIT_RANGES.maxConcurrentRuns, "runs");
  if (runs) errors.maxConcurrentRuns = runs;
  const tokens = checkWhole(values.dailyTokenQuota, LIMIT_RANGES.dailyTokenQuota, "tokens");
  if (tokens) errors.dailyTokenQuota = tokens;

  const cost = values.dailyCostQuota.trim();
  if (cost) {
    if (!DECIMAL.test(cost) || Number(cost) <= 0) {
      errors.dailyCostQuota = "Enter an amount in US dollars greater than 0, or leave it empty.";
    } else if (Number(cost) > LIMIT_RANGES.dailyCostQuotaUsd.max) {
      errors.dailyCostQuota = `Use at most $${LIMIT_RANGES.dailyCostQuotaUsd.max.toLocaleString("en")}.`;
    }
  }
  return errors;
}

/** The API's shape for these values. Call only after validation passes. */
export function toLimitsInput(values: LimitsFormValues): OrgLimitsInput {
  const cost = values.dailyCostQuota.trim();
  return {
    max_concurrent_runs: Number(values.maxConcurrentRuns.trim().replace(/,/g, "")),
    daily_token_quota: Number(values.dailyTokenQuota.trim().replace(/,/g, "")),
    daily_cost_quota_usd: cost ? Number(cost) : null,
  };
}

export function sameLimits(a: LimitsFormValues, b: LimitsFormValues): boolean {
  const norm = (v: LimitsFormValues) =>
    [v.maxConcurrentRuns, v.dailyTokenQuota, v.dailyCostQuota].map((t) =>
      t.trim().replace(/,/g, ""),
    );
  return norm(a).join("|") === norm(b).join("|");
}
