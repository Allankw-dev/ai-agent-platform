"use client";

import { ErrorNotice } from "@/components/error-notice";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { LimitsForm, LimitsSummary } from "@/features/usage/limits-form";
import { useUsage } from "@/lib/api/queries";
import type { Usage, UsageDay } from "@/lib/api/types";
import { canManageLimits, canViewUsage } from "@/lib/permissions";

const number = (value: number) => value.toLocaleString("en");
const dollars = (value: number) => `$${value.toFixed(value < 1 ? 4 : 2)}`;
const total = (item: { input_tokens: number; output_tokens: number }) =>
  item.input_tokens + item.output_tokens;

export function UsagePage() {
  const org = useCurrentOrg();
  if (!canViewUsage(org.role)) {
    return (
      <Card className="max-w-2xl">
        <CardContent className="p-6 text-sm text-muted-foreground">
          Only owners, admins and developers can see usage.
        </CardContent>
      </Card>
    );
  }
  return <UsageView orgId={org.id} mayManage={canManageLimits(org.role)} />;
}

function UsageView({ orgId, mayManage }: { orgId: string; mayManage: boolean }) {
  const usage = useUsage(orgId);
  return (
    <div className="max-w-4xl space-y-6">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Usage</h2>
        <p className="text-sm text-muted-foreground">
          What this organization&apos;s agents have used, measured from real model calls, and the
          limits that keep it in check.
        </p>
      </div>
      {usage.isPending && <Spinner label="Loading usage" />}
      <ErrorNotice error={usage.error} />
      {usage.data && (
        <>
          <Today usage={usage.data} />
          {mayManage ? (
            <LimitsForm orgId={orgId} limits={usage.data.limits} />
          ) : (
            <LimitsSummary limits={usage.data.limits} />
          )}
          <History days={usage.data.days} />
          <ByAgent usage={usage.data} />
        </>
      )}
    </div>
  );
}

function Bar({
  label,
  used,
  held,
  quota,
}: {
  label: string;
  used: number;
  held: number;
  quota: number;
}) {
  const percent = (value: number) => Math.min(100, (value / quota) * 100);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={quota}
      aria-valuenow={Math.min(used, quota)}
      className="flex h-2 w-full overflow-hidden rounded-full bg-muted"
    >
      <div className="h-full bg-primary" style={{ width: `${percent(used)}%` }} />
      <div
        className="h-full bg-primary/40"
        style={{ width: `${Math.min(percent(held), 100 - percent(used))}%` }}
      />
    </div>
  );
}

function Today({ usage }: { usage: Usage }) {
  const { today, limits } = usage;
  const used = total(today);
  const resets = new Date(today.resets_at).toLocaleTimeString("en", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Today</CardTitle>
        <CardDescription>The daily quota resets at {resets} UTC.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
            <span>
              <span className="font-medium">{number(used)}</span> of{" "}
              {number(limits.daily_token_quota)} tokens used
            </span>
            {today.reserved_tokens > 0 && (
              <span className="text-xs text-muted-foreground">
                {number(today.reserved_tokens)} more held by runs in progress
              </span>
            )}
          </div>
          <Bar
            label="Tokens used today"
            used={used}
            held={today.reserved_tokens}
            quota={limits.daily_token_quota}
          />
          <p className="text-xs text-muted-foreground">
            {number(today.input_tokens)} in, {number(today.output_tokens)} out. A run holds its
            whole token limit until it ends, so new runs are refused when used plus held would pass
            the quota.
          </p>
        </div>

        <dl className="grid gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted-foreground">Runs queued or running</dt>
            <dd>
              <span className="font-medium">{today.busy_runs}</span> of{" "}
              {number(limits.max_concurrent_runs)} allowed
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Estimated cost today</dt>
            <dd>
              <span className="font-medium">{dollars(today.cost_usd)}</span>
              {limits.daily_cost_quota_usd != null && <> of ${limits.daily_cost_quota_usd}</>}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function shortDate(day: string) {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function History({ days }: { days: UsageDay[] }) {
  const peak = Math.max(1, ...days.map(total));
  const tokens = days.reduce((sum, day) => sum + total(day), 0);
  const runs = days.reduce((sum, day) => sum + day.runs, 0);
  const cost = days.reduce((sum, day) => sum + day.cost_usd, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Last {days.length} days</CardTitle>
        <CardDescription>
          {number(runs)} runs, {number(tokens)} tokens, about {dollars(cost)}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tokens === 0 ? (
          <p className="text-sm text-muted-foreground">
            No usage yet. Start a run and it appears here.
          </p>
        ) : (
          <ul className="flex h-32 items-end gap-1" aria-label="Tokens used per day">
            {days.map((day) => (
              <li
                key={day.day}
                className="flex h-full min-w-0 flex-1 items-end"
                aria-label={`${shortDate(day.day)}: ${number(total(day))} tokens, ${day.runs} runs`}
                title={`${shortDate(day.day)}: ${number(total(day))} tokens, ${day.runs} runs`}
              >
                <div
                  className="w-full rounded-t bg-primary/70"
                  style={{
                    height: `${Math.max(total(day) > 0 ? 4 : 0, (total(day) / peak) * 100)}%`,
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ByAgent({ usage }: { usage: Usage }) {
  if (usage.by_agent.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Heaviest agents</CardTitle>
        <CardDescription>Over the last {usage.days.length} days.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="py-1 pr-4 font-medium">
                Agent
              </th>
              <th scope="col" className="py-1 pr-4 text-right font-medium">
                Tokens
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Estimated cost
              </th>
            </tr>
          </thead>
          <tbody>
            {usage.by_agent.map((agent) => (
              <tr key={agent.agent_id} className="border-t border-border">
                <th scope="row" className="py-2 pr-4 font-medium">
                  {agent.agent_name}
                </th>
                <td className="py-2 pr-4 text-right">{number(total(agent))}</td>
                <td className="py-2 text-right">{dollars(agent.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
