import { Badge, type BadgeProps } from "@/components/ui/badge";
import { STATUS_LABELS } from "@/features/approvals/approval-format";
import type { ApprovalStatus } from "@/lib/api/types";

const VARIANTS: Record<ApprovalStatus, NonNullable<BadgeProps["variant"]>> = {
  pending: "accent",
  approved: "success",
  rejected: "danger",
  expired: "muted",
  cancelled: "muted",
};

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  return <Badge variant={VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>;
}
