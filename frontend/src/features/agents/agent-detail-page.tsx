"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AgentStatusBadge } from "@/features/agents/agent-status-badge";
import { ConfigSummary } from "@/features/agents/config-summary";
import { VersionHistory } from "@/features/agents/version-history";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { ApiError } from "@/lib/api-client";
import { useAgent, useDeleteAgent, useDuplicateAgent, useUpdateAgent } from "@/lib/api/queries";
import type { AgentStatus } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { canManageAgents } from "@/lib/permissions";

const TOGGLE: Record<AgentStatus, { label: string; next: "active" | "disabled" } | null> = {
  draft: { label: "Activate", next: "active" },
  active: { label: "Disable", next: "disabled" },
  disabled: { label: "Enable", next: "active" },
  archived: null,
};

export function AgentDetailPage() {
  const org = useCurrentOrg();
  const router = useRouter();
  const { agentId } = useParams<{ agentId: string }>();
  const agent = useAgent(org.id, agentId);
  const update = useUpdateAgent(org.id, agentId);
  const duplicate = useDuplicateAgent(org.id);
  const remove = useDeleteAgent(org.id);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const mayManage = canManageAgents(org.role);

  if (agent.isPending && !agent.error) return <Spinner label="Loading agent" />;

  if (agent.error instanceof ApiError && agent.error.status === 404) {
    return (
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Agent not found</CardTitle>
          <CardDescription>It may have been deleted.</CardDescription>
          <div className="pt-4">
            <Link
              href={`/orgs/${org.id}/agents`}
              className={buttonVariants({ variant: "outline" })}
            >
              Back to agents
            </Link>
          </div>
        </CardHeader>
      </Card>
    );
  }
  if (agent.error || !agent.data) return <ErrorNotice error={agent.error} />;

  const data = agent.data;
  const toggle = TOGGLE[data.status];
  const busy = update.isPending || duplicate.isPending || remove.isPending;

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-xl font-semibold">{data.name}</h2>
            <AgentStatusBadge status={data.status} />
          </div>
          {data.description && <p className="text-sm text-muted-foreground">{data.description}</p>}
          <p className="text-xs text-muted-foreground">
            Updated {formatDateTime(data.updated_at)}
            {data.current_version ? ` · version ${data.current_version.version}` : ""}
          </p>
        </div>
        {mayManage && (
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/orgs/${org.id}/agents/${data.id}/edit`}
              className={buttonVariants({ variant: "default" })}
            >
              Edit
            </Link>
            {toggle && (
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => update.mutate({ status: toggle.next })}
              >
                {toggle.label}
              </Button>
            )}
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                duplicate.mutate(data.id, {
                  onSuccess: (copy) => router.push(`/orgs/${org.id}/agents/${copy.id}`),
                })
              }
            >
              Duplicate
            </Button>
            {confirmingDelete ? (
              <>
                <Button
                  variant="outline"
                  className="border-danger/60 text-danger hover:bg-danger/10"
                  disabled={busy}
                  onClick={() =>
                    remove.mutate(data.id, {
                      onSuccess: () => router.replace(`/orgs/${org.id}/agents`),
                    })
                  }
                >
                  Confirm delete
                </Button>
                <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button variant="ghost" disabled={busy} onClick={() => setConfirmingDelete(true)}>
                Delete
              </Button>
            )}
          </div>
        )}
      </div>

      <ErrorNotice error={update.error ?? duplicate.error ?? remove.error} />

      <Card>
        <CardHeader>
          <CardTitle>Current configuration</CardTitle>
          <CardDescription>What runs use right now.</CardDescription>
        </CardHeader>
        <CardContent>
          {data.current_version ? (
            <ConfigSummary version={data.current_version} />
          ) : (
            <p className="text-sm text-muted-foreground">This agent has no version yet.</p>
          )}
        </CardContent>
      </Card>

      <VersionHistory
        orgId={org.id}
        agentId={data.id}
        currentVersionId={data.current_version?.id ?? null}
        canManage={mayManage}
      />
    </div>
  );
}
