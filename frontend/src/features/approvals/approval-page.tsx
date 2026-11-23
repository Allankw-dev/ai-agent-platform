"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { TextareaField } from "@/components/ui/textarea";
import { ActionPreview } from "@/features/approvals/action-preview";
import { ApprovalStatusBadge } from "@/features/approvals/approval-status-badge";
import { ExpiryText } from "@/features/approvals/expiry-text";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { ApiError } from "@/lib/api-client";
import { useApproval, useDecideApproval } from "@/lib/api/queries";
import type { Approval } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { canDecideApprovals, canViewApprovals } from "@/lib/permissions";

const MAX_NOTE = 500;

type Decision = "approve" | "reject";

export function ApprovalPage() {
  const org = useCurrentOrg();
  const { approvalId } = useParams<{ approvalId: string }>();
  if (!canViewApprovals(org.role)) {
    return (
      <Card className="max-w-2xl">
        <CardContent className="p-6 text-sm text-muted-foreground">
          Only owners, admins and developers can see approvals.
        </CardContent>
      </Card>
    );
  }
  return (
    <ApprovalView orgId={org.id} approvalId={approvalId} mayDecide={canDecideApprovals(org.role)} />
  );
}

function BackLink({ orgId }: { orgId: string }) {
  return (
    <Link
      href={`/orgs/${orgId}/approvals`}
      className="text-sm text-muted-foreground hover:text-foreground"
    >
      ← All approvals
    </Link>
  );
}

function ApprovalView({
  orgId,
  approvalId,
  mayDecide,
}: {
  orgId: string;
  approvalId: string;
  mayDecide: boolean;
}) {
  const approval = useApproval(orgId, approvalId);
  const decide = useDecideApproval(orgId, approvalId);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [last, setLast] = useState<Decision | null>(null);

  if (approval.isPending && !approval.error) return <Spinner label="Loading approval" />;
  if (approval.error instanceof ApiError && approval.error.status === 404) {
    return (
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Approval not found</CardTitle>
          <CardDescription>
            It may belong to another organization, or no longer exist.
          </CardDescription>
          <div className="pt-3">
            <BackLink orgId={orgId} />
          </div>
        </CardHeader>
      </Card>
    );
  }
  if (approval.error || !approval.data) return <ErrorNotice error={approval.error} />;

  const data = approval.data;
  const waiting = data.status === "pending";

  function submit(decision: Decision) {
    setLast(decision);
    decide.mutate(
      { decision, note: note.trim() || undefined },
      {
        onSuccess: () => {
          setNote("");
          setConfirming(false);
        },
      },
    );
  }

  // The decision was saved but the run could not be handed to a worker (the queue was down):
  // pressing the same button again hands it over, so offer exactly that.
  const handOverFailed =
    decide.error instanceof ApiError && decide.error.code === "queue_unavailable" && last !== null;

  return (
    <div className="max-w-3xl space-y-6">
      <BackLink orgId={orgId} />

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">{data.tool_name ?? data.tool_key}</h2>
          <ApprovalStatusBadge status={data.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          Requested by{" "}
          <Link href={`/orgs/${orgId}/agents/${data.agent_id}`} className="hover:text-accent">
            {data.agent_name}
          </Link>{" "}
          (version {data.agent_version}) on {formatDateTime(data.requested_at)}.{" "}
          {waiting && <ExpiryText approval={data} />}
          {waiting && "."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {waiting ? "What will run if you approve" : "What was proposed"}
          </CardTitle>
          <CardDescription>
            This is exactly what runs, nothing more and nothing different.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ActionPreview toolKey={data.tool_key} input={data.proposed_input} />
        </CardContent>
      </Card>

      {data.reasoning_summary && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Why the agent asked</CardTitle>
            <CardDescription>
              The agent&apos;s own explanation. It is not checked, so judge the action above, not
              this.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap break-words text-sm">{data.reasoning_summary}</p>
          </CardContent>
        </Card>
      )}

      {/* Outside the decision box on purpose: when a click is refused because someone else
          decided first, the box disappears as the page refreshes, and the reason must not. */}
      <ErrorNotice error={handOverFailed ? null : decide.error} />

      {waiting && mayDecide && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Your decision</CardTitle>
            <CardDescription>
              Approving lets the run continue and carries out the action once. Rejecting tells the
              agent a person said no. A note is shown to the agent.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <TextareaField
              id="decision-note"
              label="Note (optional)"
              value={note}
              maxLength={MAX_NOTE}
              hint={`${note.length} of ${MAX_NOTE} characters`}
              onChange={(event) => setNote(event.target.value)}
            />
            {confirming ? (
              <div className="space-y-3">
                <p className="text-sm font-medium">Approve and run this action now?</p>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={decide.isPending} onClick={() => submit("approve")}>
                    {decide.isPending ? "Approving…" : "Yes, approve and run it"}
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={decide.isPending}
                    onClick={() => setConfirming(false)}
                  >
                    Back
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button disabled={decide.isPending} onClick={() => setConfirming(true)}>
                  Approve
                </Button>
                <Button
                  variant="outline"
                  disabled={decide.isPending}
                  onClick={() => submit("reject")}
                >
                  {decide.isPending && last === "reject" ? "Rejecting…" : "Reject"}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {waiting && !mayDecide && (
        <Alert variant="info">
          Only owners and admins can approve or reject. Ask one of them to decide.
        </Alert>
      )}

      {!waiting && <Outcome approval={data} orgId={orgId} />}

      {handOverFailed && (
        <Alert variant="error">
          <div className="space-y-2">
            <p>
              {decide.error instanceof ApiError
                ? decide.error.message
                : "The run could not continue."}
            </p>
            <Button size="sm" disabled={decide.isPending} onClick={() => last && submit(last)}>
              Try again
            </Button>
          </div>
        </Alert>
      )}
    </div>
  );
}

function Outcome({ approval, orgId }: { approval: Approval; orgId: string }) {
  const who = approval.decided_by_name ? ` by ${approval.decided_by_name}` : "";
  const when = approval.decided_at ? ` on ${formatDateTime(approval.decided_at)}` : "";
  const messages: Record<string, string> = {
    approved: `Approved${who}${when}. The action ran once, as shown above.`,
    rejected: `Rejected${who}${when}. The agent was told a person said no, and nothing ran.`,
    expired: "Nobody decided in time, so the action was not run and the run was stopped.",
    cancelled: "The run ended before anyone decided, so the action was not run.",
  };
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <p className="text-sm">{messages[approval.status]}</p>
        {approval.decision_note && (
          <p className="whitespace-pre-wrap break-words text-sm text-muted-foreground">
            Note: {approval.decision_note}
          </p>
        )}
        <Link
          href={`/orgs/${orgId}/runs/${approval.run_id}`}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          Open the run
        </Link>
      </CardContent>
    </Card>
  );
}
