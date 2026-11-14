import { Badge } from "@/components/ui/badge";
import type { RunStatus, StepStatus } from "@/lib/api/types";

const RUN_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  awaiting_approval: "Waiting for approval",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

const RUN_VARIANTS: Record<RunStatus, "muted" | "accent" | "success" | "danger"> = {
  queued: "muted",
  running: "accent",
  awaiting_approval: "accent",
  succeeded: "success",
  failed: "danger",
  cancelled: "muted",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge variant={RUN_VARIANTS[status]}>{RUN_LABELS[status]}</Badge>;
}

const STEP_LABELS: Record<StepStatus, string> = {
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  skipped: "Skipped",
};

const STEP_VARIANTS: Record<StepStatus, "muted" | "accent" | "success" | "danger"> = {
  running: "accent",
  succeeded: "success",
  failed: "danger",
  skipped: "muted",
};

export function StepStatusBadge({ status }: { status: StepStatus }) {
  return <Badge variant={STEP_VARIANTS[status]}>{STEP_LABELS[status]}</Badge>;
}
