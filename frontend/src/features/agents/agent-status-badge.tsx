import { Badge } from "@/components/ui/badge";
import type { AgentStatus } from "@/lib/api/types";

const LABELS: Record<AgentStatus, string> = {
  draft: "Draft",
  active: "Active",
  disabled: "Disabled",
  archived: "Archived",
};

const VARIANTS: Record<AgentStatus, "muted" | "success" | "danger" | "accent"> = {
  draft: "accent",
  active: "success",
  disabled: "muted",
  archived: "muted",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return <Badge variant={VARIANTS[status]}>{LABELS[status]}</Badge>;
}
