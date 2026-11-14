import { StepStatusBadge } from "@/features/runs/run-status-badge";
import type { RunStepRead, StepType } from "@/lib/api/types";
import { formatDuration } from "@/lib/format";

const TYPE_LABELS: Record<StepType, string> = {
  llm_call: "Model call",
  tool_call: "Tool call",
  approval: "Approval",
  error: "Error",
};

function Json({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-background p-3 text-xs whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

/** One line saying what the step did, so the timeline reads without opening anything. */
function summarize(step: RunStepRead): string | null {
  if (step.step_type === "llm_call" && step.output) {
    const calls = (step.output.tool_calls as { name: string }[] | undefined) ?? [];
    if (calls.length > 0) return `Asked to use: ${calls.map((call) => call.name).join(", ")}`;
    const text = typeof step.output.text === "string" ? step.output.text.trim() : "";
    if (text) return text.length > 160 ? `${text.slice(0, 160)}…` : text;
  }
  return null;
}

export function StepTimeline({ steps }: { steps: RunStepRead[] }) {
  if (steps.length === 0) {
    return <p className="text-sm text-muted-foreground">No steps yet.</p>;
  }
  return (
    <ol className="space-y-3">
      {steps.map((step) => {
        const summary = summarize(step);
        const duration = formatDuration(step.started_at, step.finished_at);
        const tokens = step.input_tokens + step.output_tokens;
        return (
          <li key={step.id} className="rounded-lg border border-border bg-background/40 p-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-xs text-muted-foreground">Step {step.sequence + 1}</span>
              <span className="text-sm font-medium">{TYPE_LABELS[step.step_type]}</span>
              {(step.tool_key || step.name) && (
                <code className="text-xs text-muted-foreground">{step.tool_key ?? step.name}</code>
              )}
              <StepStatusBadge status={step.status} />
              <span className="ml-auto text-xs text-muted-foreground">
                {[duration, tokens > 0 ? `${tokens.toLocaleString("en")} tokens` : ""]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </div>
            {summary && <p className="mt-2 text-sm whitespace-pre-wrap">{summary}</p>}
            {step.error && (
              <p role="alert" className="mt-2 text-sm text-danger">
                {step.error}
              </p>
            )}
            {(step.input || step.output) && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-accent">Details</summary>
                <div className="mt-2 space-y-3">
                  {step.input && <Json label="Input" value={step.input} />}
                  {step.output && <Json label="Output" value={step.output} />}
                </div>
              </details>
            )}
          </li>
        );
      })}
    </ol>
  );
}
