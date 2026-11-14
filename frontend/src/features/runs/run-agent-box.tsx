"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TextareaField } from "@/components/ui/textarea";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { useStartRun } from "@/lib/api/queries";
import type { AgentStatus } from "@/lib/api/types";
import { newIdempotencyKey } from "@/lib/format";
import { canRunAgents } from "@/lib/permissions";

const MAX_MESSAGE = 20_000;

type Props = { agentId: string; status: AgentStatus; version: number | null };

/** "Run this agent": a message box on the agent's page. Starting a run opens its run page. */
export function RunAgentBox({ agentId, status, version }: Props) {
  const org = useCurrentOrg();
  const router = useRouter();
  const start = useStartRun(org.id, agentId);
  const [message, setMessage] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  // One key per message: a double click returns the same run instead of starting two.
  const key = useRef(newIdempotencyKey());

  if (!canRunAgents(org.role)) {
    return (
      <p className="text-sm text-muted-foreground">
        Only owners, admins and developers can run agents. You can open any run to see what
        happened.
      </p>
    );
  }
  if (status !== "draft" && status !== "active") {
    return (
      <p className="text-sm text-muted-foreground">This agent is {status}. Enable it to run it.</p>
    );
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!message.trim()) return setProblem("Write a message for the agent.");
    if (message.length > MAX_MESSAGE) return setProblem("Use at most 20,000 characters.");
    setProblem(null);
    start.mutate(
      { message, idempotencyKey: key.current },
      {
        onSuccess: (run) => {
          key.current = newIdempotencyKey();
          router.push(`/orgs/${org.id}/runs/${run.id}`);
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Run this agent</CardTitle>
        <CardDescription>
          Give it a task. It runs with the current version
          {version ? ` (version ${version})` : ""} and you can watch each step.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} noValidate className="space-y-3">
          <TextareaField
            id="run-message"
            label="Message"
            rows={3}
            value={message}
            error={problem}
            hint="For example: What is 16% VAT on KES 12,500, and what is the total?"
            onChange={(event) => {
              setMessage(event.target.value);
              key.current = newIdempotencyKey();
            }}
          />
          <ErrorNotice error={start.error} />
          <Button type="submit" disabled={start.isPending}>
            {start.isPending ? "Starting…" : "Run agent"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
