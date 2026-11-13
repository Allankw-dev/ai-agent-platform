import { Badge } from "@/components/ui/badge";
import type { VersionRead } from "@/lib/api/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[10rem_1fr] sm:gap-4">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  );
}

/** A read-only view of one version's settings. */
export function ConfigSummary({ version }: { version: VersionRead }) {
  const { limits } = version;
  const maxOutput = version.model_params.max_output_tokens;
  return (
    <dl className="space-y-4">
      <Row label="Model">
        {version.model} <span className="text-muted-foreground">({version.provider})</span>
      </Row>
      <Row label="Instructions">
        <div className="max-h-64 overflow-auto rounded-lg border border-border bg-background p-3 whitespace-pre-wrap">
          {version.system_instructions}
        </div>
      </Row>
      {version.objectives && (
        <Row label="Objectives">
          <div className="max-h-40 overflow-auto whitespace-pre-wrap">{version.objectives}</div>
        </Row>
      )}
      <Row label="Tools">
        {version.tools.length === 0 ? (
          <span className="text-muted-foreground">
            No tools: the agent can only answer in text.
          </span>
        ) : (
          <ul className="space-y-2">
            {version.tools.map((tool) => (
              <li key={tool.tool_key} className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{tool.name}</span>
                <code className="text-xs text-muted-foreground">{tool.tool_key}</code>
                {(tool.is_sensitive || tool.requires_approval) && (
                  <Badge variant="muted">Needs approval</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </Row>
      <Row label="Limits per run">
        {limits.max_iterations ?? "–"} model calls, {limits.timeout_seconds ?? "–"} s,{" "}
        {limits.max_total_tokens?.toLocaleString("en") ?? "–"} tokens, cost budget{" "}
        {limits.cost_budget_usd == null ? "none" : `$${limits.cost_budget_usd}`}
      </Row>
      <Row label="Max reply length">
        {maxOutput == null ? "Model default" : `${maxOutput.toLocaleString("en")} tokens`}
      </Row>
    </dl>
  );
}
