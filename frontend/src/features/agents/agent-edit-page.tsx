"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { AgentForm } from "@/features/agents/agent-form";
import { NoAgentPermission } from "@/features/agents/agent-create-page";
import { valuesFromAgent } from "@/features/agents/agent-form-model";
import { useSaveAgent } from "@/features/agents/use-save-agent";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { ApiError } from "@/lib/api-client";
import { useAgent } from "@/lib/api/queries";
import type { AgentRead } from "@/lib/api/types";
import { canManageAgents } from "@/lib/permissions";

function EditForm({ orgId, agent }: { orgId: string; agent: AgentRead }) {
  const router = useRouter();
  const { save, pending, error } = useSaveAgent(orgId, agent);
  const [notice, setNotice] = useState<string | null>(null);
  const back = `/orgs/${orgId}/agents/${agent.id}`;

  return (
    <AgentForm
      mode="edit"
      initial={valuesFromAgent(agent)}
      submitLabel="Save changes"
      submittingLabel="Saving…"
      submitting={pending}
      error={error}
      notice={notice}
      cancelHref={back}
      onSubmit={async (values) => {
        setNotice(null);
        const result = await save(values);
        if (result === "saved") router.push(back);
        if (result === "unchanged") setNotice("Nothing to save: you have not changed anything.");
      }}
    />
  );
}

export function AgentEditPage() {
  const org = useCurrentOrg();
  const { agentId } = useParams<{ agentId: string }>();
  const agent = useAgent(org.id, agentId);

  if (!canManageAgents(org.role)) return <NoAgentPermission orgId={org.id} />;
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

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Edit {agent.data.name}</h2>
      {/* Keyed by version so the form restarts from the saved values after a rollback elsewhere. */}
      <EditForm
        key={`${agent.data.id}:${agent.data.current_version?.id ?? "none"}`}
        orgId={org.id}
        agent={agent.data}
      />
    </div>
  );
}
