"use client";

import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import {
  LIMIT_RANGES,
  sameLimits,
  toLimitsInput,
  validateLimits,
  valuesFromLimits,
  type LimitsFormErrors,
  type LimitsFormValues,
} from "@/features/usage/limits-form-model";
import { useResetOrgLimits, useSaveOrgLimits } from "@/lib/api/queries";
import type { OrgLimits } from "@/lib/api/types";

const DANGER = "border-danger/40 text-danger hover:bg-danger/10";

/** Owners and admins change the organization's limits here. Others see them in LimitsSummary. */
export function LimitsForm({ orgId, limits }: { orgId: string; limits: OrgLimits }) {
  const saved = valuesFromLimits(limits);
  const [values, setValues] = useState<LimitsFormValues>(saved);
  const [errors, setErrors] = useState<LimitsFormErrors>({});
  // When the saved limits change (after a save or a reset, or someone else changing them), the
  // form starts again from them. This is done while rendering, not in an effect, so there is no
  // flash of the old values; the notice and other state are kept.
  const [seen, setSeen] = useState(JSON.stringify(limits));
  if (seen !== JSON.stringify(limits)) {
    setSeen(JSON.stringify(limits));
    setValues(saved);
    setErrors({});
  }
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const save = useSaveOrgLimits(orgId);
  const reset = useResetOrgLimits(orgId);

  const change =
    (field: keyof LimitsFormValues) => (event: React.ChangeEvent<HTMLInputElement>) => {
      setValues((current) => ({ ...current, [field]: event.target.value }));
      setNotice(null);
      save.reset();
    };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const found = validateLimits(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate(toLimitsInput(values), {
      onSuccess: () => setNotice("Limits saved. They apply to runs started from now on."),
    });
  };

  const unchanged = sameLimits(values, saved);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Run limits</CardTitle>
        <CardDescription>
          {limits.customized
            ? "Set by an owner or admin for this organization."
            : "The platform defaults. Save to set your own."}{" "}
          A run reserves its token limit against the daily quota when it starts, and gives back what
          it does not use when it ends.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} noValidate className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field
              id="limit-concurrent"
              label="Runs at once"
              inputMode="numeric"
              value={values.maxConcurrentRuns}
              onChange={change("maxConcurrentRuns")}
              error={errors.maxConcurrentRuns}
              hint={`Queued or running. ${LIMIT_RANGES.maxConcurrentRuns.min} to ${LIMIT_RANGES.maxConcurrentRuns.max.toLocaleString("en")}.`}
            />
            <Field
              id="limit-daily-tokens"
              label="Tokens per day"
              inputMode="numeric"
              value={values.dailyTokenQuota}
              onChange={change("dailyTokenQuota")}
              error={errors.dailyTokenQuota}
              hint="Resets at midnight UTC."
            />
            <Field
              id="limit-daily-cost"
              label="Cost per day in US dollars (optional)"
              inputMode="decimal"
              value={values.dailyCostQuota}
              onChange={change("dailyCostQuota")}
              error={errors.dailyCostQuota}
              hint="Needs model prices set on the server, or agents without a cost budget are refused."
            />
          </div>

          <ErrorNotice error={save.error ?? reset.error} />
          {notice && (
            <p role="status" className="text-sm text-success">
              {notice}
            </p>
          )}

          {!confirmingReset ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={save.isPending || unchanged}>
                {save.isPending ? "Saving…" : "Save limits"}
              </Button>
              {limits.customized && (
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    reset.reset();
                    setConfirmingReset(true);
                  }}
                >
                  Reset to platform defaults
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm">
                Go back to the platform defaults? Runs already started are not affected.
              </p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className={DANGER}
                  disabled={reset.isPending}
                  onClick={() =>
                    reset.mutate(undefined, {
                      onSuccess: () => {
                        setConfirmingReset(false);
                        setErrors({});
                        setNotice("Back to the platform defaults.");
                      },
                    })
                  }
                >
                  Confirm reset
                </Button>
                <Button type="button" variant="ghost" onClick={() => setConfirmingReset(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </form>
      </CardContent>
    </Card>
  );
}

/** The limits as plain text, for people who may see but not change them. */
export function LimitsSummary({ limits }: { limits: OrgLimits }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Run limits</CardTitle>
        <CardDescription>
          {limits.customized ? "Set by an owner or admin." : "The platform defaults."} Only owners
          and admins can change them.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted-foreground">Runs at once</dt>
            <dd>{limits.max_concurrent_runs.toLocaleString("en")}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Tokens per day</dt>
            <dd>{limits.daily_token_quota.toLocaleString("en")}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Cost per day</dt>
            <dd>
              {limits.daily_cost_quota_usd == null ? "No limit" : `$${limits.daily_cost_quota_usd}`}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
