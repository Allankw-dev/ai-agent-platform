"use client";

import { useState } from "react";
import Link from "next/link";

import { ErrorNotice } from "@/components/error-notice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { ApprovalStatusBadge } from "@/features/approvals/approval-status-badge";
import { summarizeAction } from "@/features/approvals/approval-format";
import { ExpiryText } from "@/features/approvals/expiry-text";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { useApprovals } from "@/lib/api/queries";
import type { ApprovalStatus } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { canDecideApprovals, canViewApprovals } from "@/lib/permissions";

const PAGE_SIZE = 20;
const STATUS_OPTIONS: { value: ApprovalStatus | ""; label: string }[] = [
  { value: "pending", label: "Waiting for a decision" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
  { value: "cancelled", label: "Cancelled" },
  { value: "", label: "All" },
];

export function ApprovalsPage() {
  const org = useCurrentOrg();
  if (!canViewApprovals(org.role)) {
    return (
      <Card className="max-w-2xl">
        <CardContent className="p-6 text-sm text-muted-foreground">
          Only owners, admins and developers can see approvals.
        </CardContent>
      </Card>
    );
  }
  return <ApprovalsList orgId={org.id} mayDecide={canDecideApprovals(org.role)} />;
}

function ApprovalsList({ orgId, mayDecide }: { orgId: string; mayDecide: boolean }) {
  const [status, setStatus] = useState<ApprovalStatus | "">("pending");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const approvals = useApprovals(orgId, { status: status || undefined, limit });

  return (
    <div className="max-w-4xl space-y-6">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Approvals</h2>
        <p className="text-sm text-muted-foreground">
          Actions your agents want to take that need a person to say yes first. Nothing runs until
          it is approved.
          {!mayDecide && " Only owners and admins can approve or reject."}
        </p>
      </div>

      <Select
        aria-label="Filter by status"
        value={status}
        onChange={(event) => {
          setStatus(event.target.value as ApprovalStatus | "");
          setLimit(PAGE_SIZE);
        }}
      >
        {STATUS_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>

      <ErrorNotice error={approvals.error} />
      {approvals.isPending && !approvals.error && <Spinner label="Loading approvals" />}

      {approvals.data && approvals.data.items.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              {status === "pending" ? "Nothing is waiting for a decision" : "No approvals here"}
            </CardTitle>
            <CardDescription>
              {status === "pending"
                ? "When an agent wants to do something that needs approval, it will appear here."
                : "Try a different status."}
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {approvals.data && approvals.data.items.length > 0 && (
        <ul className="space-y-3">
          {approvals.data.items.map((approval) => (
            <li key={approval.id}>
              <Card className="transition-colors hover:border-accent/60">
                <CardContent className="space-y-2 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href={`/orgs/${orgId}/approvals/${approval.id}`}
                      className="font-medium hover:text-accent"
                    >
                      {approval.tool_name ?? approval.tool_key}
                    </Link>
                    <ApprovalStatusBadge status={approval.status} />
                    <span className="ml-auto text-xs text-muted-foreground">
                      {formatDateTime(approval.requested_at)}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {approval.agent_name} · v{approval.agent_version}
                  </p>
                  <p className="line-clamp-2 break-words text-sm">
                    {summarizeAction(approval.tool_key, approval.proposed_input)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {approval.status === "pending" ? (
                      <ExpiryText approval={approval} />
                    ) : approval.decided_by_name ? (
                      `${approval.status === "approved" ? "Approved" : "Rejected"} by ${approval.decided_by_name}`
                    ) : null}
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {approvals.data && approvals.data.total > approvals.data.items.length && (
        <Button variant="outline" size="sm" onClick={() => setLimit((value) => value + PAGE_SIZE)}>
          Show more
        </Button>
      )}
    </div>
  );
}
