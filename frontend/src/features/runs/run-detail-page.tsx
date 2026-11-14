"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { RunStatusBadge } from "@/features/runs/run-status-badge";
import { StepTimeline } from "@/features/runs/step-timeline";
import { ApiError } from "@/lib/api-client";
import { isActiveRun, useCancelRun, useRun, useStartRun } from "@/lib/api/queries";
import type { RunDetail } from "@/lib/api/types";
import { formatCost, formatDateTime, formatDuration, newIdempotencyKey } from "@/lib/format";
import { canRunAgents } from "@/lib/permissions";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function Outcome({ run }: { run: RunDetail }) {
  const text = run.output?.text?.trim();
  if (isActiveRun(run.status)) {
    return (
      <div className="space-y-2">
        <Spinner
          label={
            run.status === "queued"
              ? "Waiting for a worker to pick this up"
              : "The agent is working"
          }
        />
        <p className="text-xs text-muted-foreground">This page updates by itself.</p>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {run.status === "failed" && <Alert variant="error">{run.error ?? "The run failed."}</Alert>}
      {run.status === "cancelled" && (
        <Alert variant="info">This run was cancelled before it finished.</Alert>
      )}
      {text ? (
        <div className="space-y-1">
          {run.status !== "succeeded" && (
            <p className="text-xs text-muted-foreground">The agent&apos;s last reply:</p>
          )}
          <p className="text-sm whitespace-pre-wrap">{text}</p>
        </div>
      ) : (
        run.status === "succeeded" && (
          <p className="text-sm text-muted-foreground">The agent returned no text.</p>
        )
      )}
    </div>
  );
}

export function RunDetailPage() {
  const org = useCurrentOrg();
  const router = useRouter();
  const { runId } = useParams<{ runId: string }>();
  const run = useRun(org.id, runId);
  const cancel = useCancelRun(org.id, runId);
  const again = useStartRun(org.id, run.data?.agent_id ?? "");
  const mayRun = canRunAgents(org.role);

  if (run.isPending && !run.error) return <Spinner label="Loading run" />;

  if (run.error instanceof ApiError && run.error.status === 404) {
    return (
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Run not found</CardTitle>
          <CardDescription>It may belong to another organization.</CardDescription>
          <div className="pt-4">
            <Link href={`/orgs/${org.id}/runs`} className={buttonVariants({ variant: "outline" })}>
              Back to runs
            </Link>
          </div>
        </CardHeader>
      </Card>
    );
  }
  if (run.error || !run.data) return <ErrorNotice error={run.error} />;

  const data = run.data;
  const active = isActiveRun(data.status);
  const tokens = data.input_tokens + data.output_tokens;
  const duration = formatDuration(data.started_at, data.finished_at);
  const message = data.input.message ?? "";

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-semibold">
              Run of{" "}
              <Link href={`/orgs/${org.id}/agents/${data.agent_id}`} className="hover:text-accent">
                {data.agent_name || "agent"}
              </Link>
            </h2>
            <RunStatusBadge status={data.status} />
          </div>
          <p className="text-xs text-muted-foreground">
            Version {data.agent_version} · started {formatDateTime(data.created_at)}
          </p>
        </div>
        {mayRun && (
          <div className="flex flex-wrap items-center gap-2">
            {active && (
              <Button variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                {cancel.isPending ? "Cancelling…" : "Cancel run"}
              </Button>
            )}
            {!active && message && (
              <Button
                variant="outline"
                disabled={again.isPending}
                onClick={() =>
                  again.mutate(
                    { message, idempotencyKey: newIdempotencyKey() },
                    {
                      onSuccess: (next) => router.push(`/orgs/${org.id}/runs/${next.id}`),
                    },
                  )
                }
              >
                {again.isPending ? "Starting…" : "Run again"}
              </Button>
            )}
          </div>
        )}
      </div>

      <ErrorNotice error={cancel.error ?? again.error} />

      <Card>
        <CardHeader>
          <CardTitle>Message</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm whitespace-pre-wrap">{message || "(no message)"}</p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Result</CardTitle>
        </CardHeader>
        <CardContent>
          <Outcome run={data} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Usage</CardTitle>
          <CardDescription>
            Costs are estimates, and need model prices to be set on the server.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-4">
            <Fact label="Tokens in">{data.input_tokens.toLocaleString("en")}</Fact>
            <Fact label="Tokens out">{data.output_tokens.toLocaleString("en")}</Fact>
            <Fact label="Estimated cost">{formatCost(data.cost_usd, tokens)}</Fact>
            <Fact label="Time taken">{duration || (active ? "In progress" : "–")}</Fact>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Steps ({data.steps.length})</CardTitle>
          <CardDescription>Every model call and tool call, in order.</CardDescription>
        </CardHeader>
        <CardContent>
          <StepTimeline steps={data.steps} />
        </CardContent>
      </Card>
    </div>
  );
}
