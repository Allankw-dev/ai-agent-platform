"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AgentForm } from "@/features/agents/agent-form";
import { emptyFormValues, toAgentConfig } from "@/features/agents/agent-form-model";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { useCreateAgent } from "@/lib/api/queries";
import { canManageAgents } from "@/lib/permissions";

export function NoAgentPermission({ orgId }: { orgId: string }) {
  return (
    <Card className="max-w-lg">
      <CardHeader>
        <CardTitle>You can view agents but not change them</CardTitle>
        <CardDescription>
          Only owners, admins and developers can create or edit agents.
        </CardDescription>
        <div className="pt-4">
          <Link href={`/orgs/${orgId}/agents`} className={buttonVariants({ variant: "outline" })}>
            Back to agents
          </Link>
        </div>
      </CardHeader>
    </Card>
  );
}

export function AgentCreatePage() {
  const org = useCurrentOrg();
  const router = useRouter();
  const create = useCreateAgent(org.id);

  if (!canManageAgents(org.role)) return <NoAgentPermission orgId={org.id} />;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Create an agent</h2>
      <AgentForm
        mode="create"
        initial={emptyFormValues()}
        submitLabel="Create agent"
        submittingLabel="Creating…"
        submitting={create.isPending}
        error={create.error}
        cancelHref={`/orgs/${org.id}/agents`}
        onSubmit={(values) =>
          create.mutate(
            {
              name: values.name.trim(),
              description: values.description.trim() || null,
              config: toAgentConfig(values),
            },
            { onSuccess: (agent) => router.push(`/orgs/${org.id}/agents/${agent.id}`) },
          )
        }
      />
    </div>
  );
}
