"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { RunStatusBadge } from "@/features/runs/run-status-badge";
import { useAgents, useRuns } from "@/lib/api/queries";
import type { RunStatus } from "@/lib/api/types";
import { formatCost, formatDateTime, formatDuration } from "@/lib/format";

const PAGE_SIZE = 20;
const STATUS_OPTIONS: { value: RunStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

export function RunsListPage() {
  const org = useCurrentOrg();
  const search = useSearchParams();
  const [agentId, setAgentId] = useState(search.get("agent") ?? "");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const agents = useAgents(org.id, { limit: 100 });
  const runs = useRuns(org.id, {
    agentId: agentId || undefined,
    status: status || undefined,
    limit,
  });
  const filtering = agentId !== "" || status !== "";
  const knownAgent = agents.data?.items.some((agent) => agent.id === agentId);

  return (
    <div className="max-w-4xl space-y-6">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Runs</h2>
        <p className="text-sm text-muted-foreground">
          {runs.data
            ? `${runs.data.total} ${runs.data.total === 1 ? "run" : "runs"}${filtering ? " match" : ""}, newest first.`
            : "Everything your agents have done."}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Filter by agent"
          value={agentId}
          onChange={(event) => {
            setAgentId(event.target.value);
            setLimit(PAGE_SIZE);
          }}
        >
          <option value="">All agents</option>
          {agentId && agents.data && !knownAgent && <option value={agentId}>This agent</option>}
          {agents.data?.items.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter by status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as RunStatus | "");
            setLimit(PAGE_SIZE);
          }}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        {filtering && (
          <Button
            variant="ghost"
            onClick={() => {
              setAgentId("");
              setStatus("");
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      <ErrorNotice error={runs.error} />
      {runs.isPending && !runs.error && <Spinner label="Loading runs" />}

      {runs.data && runs.data.items.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{filtering ? "No runs match" : "No runs yet"}</CardTitle>
            <CardDescription>
              {filtering
                ? "Try different filters."
                : "Open an agent and use “Run this agent” to start one."}
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {runs.data && runs.data.items.length > 0 && (
        <ul className="space-y-3">
          {runs.data.items.map((run) => {
            const duration = formatDuration(run.started_at, run.finished_at);
            return (
              <li key={run.id}>
                <Card className="transition-colors hover:border-accent/60">
                  <CardContent className="space-y-2 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/orgs/${org.id}/runs/${run.id}`}
                        className="font-medium hover:text-accent"
                      >
                        {run.agent_name || "Agent"}
                      </Link>
                      <span className="text-xs text-muted-foreground">v{run.agent_version}</span>
                      <RunStatusBadge status={run.status} />
                      <span className="ml-auto text-xs text-muted-foreground">
                        {formatDateTime(run.created_at)}
                      </span>
                    </div>
                    {run.input.message && (
                      <p className="line-clamp-2 text-sm text-muted-foreground">
                        {run.input.message}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {[
                        duration,
                        `${(run.input_tokens + run.output_tokens).toLocaleString("en")} tokens`,
                        `cost: ${formatCost(run.cost_usd, run.input_tokens + run.output_tokens)}`,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {runs.data && runs.data.total > runs.data.items.length && (
        <Button variant="outline" size="sm" onClick={() => setLimit((value) => value + PAGE_SIZE)}>
          Show more
        </Button>
      )}
    </div>
  );
}
