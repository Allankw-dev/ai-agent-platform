"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { TextareaField } from "@/components/ui/textarea";
import {
  LIMITS,
  MODEL_SUGGESTIONS,
  autoChooseIntegrations,
  integrationIdOf,
  validateAgentForm,
  type AgentFormValues,
  type ToolSelection,
} from "@/features/agents/agent-form-model";
import { PROVIDER_LABELS, describeSettings } from "@/features/integrations/integration-form-model";
import { useIntegrations, useTools } from "@/lib/api/queries";
import type { Integration, ToolInfo } from "@/lib/api/types";

type Props = {
  mode: "create" | "edit";
  /** The organization, needed to list the integrations a tool can use. */
  orgId: string;
  initial: AgentFormValues;
  submitLabel: string;
  submittingLabel: string;
  submitting: boolean;
  error: unknown;
  /** Shown above the form, e.g. "Nothing to save". */
  notice?: string | null;
  cancelHref: string;
  onSubmit: (values: AgentFormValues) => void;
};

type IntegrationList = {
  items: Integration[] | undefined;
  loading: boolean;
  error: unknown;
};

/** Which integration a tool should use. Only active integrations of the right type are offered. */
function IntegrationChoice({
  tool,
  choice,
  orgId,
  integrations,
  onPick,
}: {
  tool: ToolInfo;
  choice: ToolSelection;
  orgId: string;
  integrations: IntegrationList;
  onPick: (integrationId: string) => void;
}) {
  const label = tool.provider ? PROVIDER_LABELS[tool.provider] : "";
  const options = (integrations.items ?? []).filter(
    (item) => item.provider === tool.provider && item.status === "active",
  );
  const current = integrationIdOf(choice);
  const chosen = options.find((item) => item.id === current);
  const gone = current !== "" && !chosen && !integrations.loading && !integrations.error;

  if (integrations.loading) {
    return <p className="ml-7 text-sm text-muted-foreground">Loading integrations…</p>;
  }
  if (integrations.error) return <ErrorNotice error={integrations.error} />;
  if (options.length === 0) {
    return (
      <p className="ml-7 text-sm text-muted-foreground">
        {gone
          ? `The ${label} integration chosen earlier is disabled or deleted. `
          : `No active ${label} integration yet. `}
        Add one in the{" "}
        <Link href={`/orgs/${orgId}/integrations`} className="text-accent underline">
          Integrations tab
        </Link>
        , then come back and choose it here.
      </p>
    );
  }
  return (
    <div className="ml-7 space-y-1.5">
      <label htmlFor={`tool-${tool.key}-integration`} className="text-sm font-medium">
        Integration for {tool.name}
      </label>
      <Select
        id={`tool-${tool.key}-integration`}
        className="w-full"
        value={chosen ? current : ""}
        onChange={(event) => onPick(event.target.value)}
      >
        <option value="">Choose an integration…</option>
        {options.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </Select>
      {chosen && <p className="text-xs text-muted-foreground">{describeSettings(chosen)}</p>}
      {gone && (
        <p className="text-xs text-danger">
          The integration chosen earlier is disabled or deleted. Choose another.
        </p>
      )}
    </div>
  );
}

function ToolPicker({
  tools,
  selected,
  orgId,
  integrations,
  onChange,
}: {
  tools: ToolInfo[];
  selected: ToolSelection[];
  orgId: string;
  integrations: IntegrationList;
  onChange: (next: ToolSelection[]) => void;
}) {
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {tools.map((tool) => {
        const choice = selected.find((entry) => entry.toolKey === tool.key);
        const approvalRequired = tool.is_sensitive || choice?.requiresApproval === true;
        return (
          <li key={tool.key} className="space-y-2 px-4 py-3">
            <div className="flex items-start gap-3">
              <input
                id={`tool-${tool.key}`}
                type="checkbox"
                className="mt-1 size-4 accent-accent"
                checked={choice !== undefined}
                aria-describedby={`tool-${tool.key}-description`}
                onChange={(event) => {
                  if (!event.target.checked) {
                    onChange(selected.filter((entry) => entry.toolKey !== tool.key));
                    return;
                  }
                  onChange([
                    ...selected,
                    {
                      toolKey: tool.key,
                      requiresApproval: tool.is_sensitive,
                      config: {},
                      provider: tool.provider,
                    },
                  ]);
                }}
              />
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <label htmlFor={`tool-${tool.key}`} className="text-sm font-medium">
                    {tool.name}
                  </label>
                  <code className="text-xs text-muted-foreground">{tool.key}</code>
                  {tool.is_sensitive && <Badge variant="muted">Sensitive</Badge>}
                </div>
                <p id={`tool-${tool.key}-description`} className="text-xs text-muted-foreground">
                  {tool.description}
                </p>
              </div>
            </div>
            {choice && tool.provider && (
              <IntegrationChoice
                tool={tool}
                choice={choice}
                orgId={orgId}
                integrations={integrations}
                onPick={(integrationId) =>
                  onChange(
                    selected.map((entry) =>
                      entry.toolKey === tool.key
                        ? {
                            ...entry,
                            config: integrationId ? { integration_id: integrationId } : {},
                          }
                        : entry,
                    ),
                  )
                }
              />
            )}
            {choice && (
              <label className="ml-7 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-accent"
                  checked={approvalRequired}
                  disabled={tool.is_sensitive}
                  aria-label={`Require approval for ${tool.name}`}
                  onChange={(event) =>
                    onChange(
                      selected.map((entry) =>
                        entry.toolKey === tool.key
                          ? { ...entry, requiresApproval: event.target.checked }
                          : entry,
                      ),
                    )
                  }
                />
                Require a person&apos;s approval before it runs
                {tool.is_sensitive && (
                  <span className="text-xs text-muted-foreground">
                    (always, for sensitive tools)
                  </span>
                )}
              </label>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** The form shared by "create an agent" and "edit an agent". */
export function AgentForm({
  mode,
  orgId,
  initial,
  submitLabel,
  submittingLabel,
  submitting,
  error,
  notice,
  cancelHref,
  onSubmit,
}: Props) {
  const tools = useTools();
  // Only fetch integrations when some tool in the catalog needs one.
  const needsIntegrations = tools.data?.some((tool) => tool.provider) ?? false;
  const integrations = useIntegrations(orgId, 100, needsIntegrations);
  const [values, setValues] = useState<AgentFormValues>(initial);

  // A tool that needs an integration gets the only fitting one chosen for the person.
  const integrationItems = integrations.data?.items;
  const resolvedTools = useMemo(
    () => autoChooseIntegrations(values.tools, integrationItems),
    [values.tools, integrationItems],
  );
  const [errors, setErrors] = useState<ReturnType<typeof validateAgentForm>>({});

  const set = <K extends keyof AgentFormValues>(key: K, value: AgentFormValues[K]) =>
    setValues((current) => ({ ...current, [key]: value }));
  const text =
    (key: keyof AgentFormValues & string) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      set(key, event.target.value as never);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const submitted = { ...values, tools: resolvedTools };
    const found = validateAgentForm(submitted, mode);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    onSubmit(submitted);
  }

  const anyApproval = values.tools.some((tool) => tool.requiresApproval);
  const hasErrors = Object.keys(errors).length > 0;

  return (
    <form onSubmit={submit} noValidate className="max-w-3xl space-y-6">
      {hasErrors && <Alert variant="error">Fix the highlighted fields and try again.</Alert>}
      {notice && <Alert variant="info">{notice}</Alert>}
      <ErrorNotice error={error} />

      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
          <CardDescription>How the agent appears to your team.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field
            id="agent-name"
            label="Name"
            value={values.name}
            onChange={text("name")}
            error={errors.name}
            maxLength={200}
          />
          <TextareaField
            id="agent-description"
            label="Description (optional)"
            value={values.description}
            onChange={text("description")}
            error={errors.description}
            className="[&_textarea]:min-h-16"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Behavior</CardTitle>
          <CardDescription>
            {mode === "edit"
              ? "Changing any of this saves a new version. Older versions are kept and can be restored."
              : "What the agent does and which model powers it."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-[12rem_1fr]">
            <div className="space-y-1.5">
              <label htmlFor="agent-provider" className="text-sm font-medium">
                Provider
              </label>
              <Select
                id="agent-provider"
                className="w-full"
                value="gemini"
                disabled
                onChange={() => {}}
              >
                <option value="gemini">Gemini</option>
              </Select>
            </div>
            <Field
              id="agent-model"
              label="Model"
              list="agent-model-suggestions"
              value={values.model}
              onChange={text("model")}
              error={errors.model}
              hint="Pick a suggestion or type any model name. Free models are sometimes overloaded: if runs fail, try another."
              autoComplete="off"
            />
            <datalist id="agent-model-suggestions">
              {MODEL_SUGGESTIONS.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </div>
          <TextareaField
            id="agent-instructions"
            label="Instructions"
            value={values.instructions}
            onChange={text("instructions")}
            error={errors.instructions}
            hint="Tell the agent its role, what it may do and how to answer."
            rows={8}
          />
          <TextareaField
            id="agent-objectives"
            label="Objectives (optional)"
            value={values.objectives}
            onChange={text("objectives")}
            error={errors.objectives}
            hint="Goals it should keep in mind. Added after the instructions."
            rows={3}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tools</CardTitle>
          <CardDescription>
            Choose what the agent is allowed to use. It can use nothing that is not ticked here.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {tools.isPending && !tools.error && <Spinner label="Loading tools" />}
          <ErrorNotice error={tools.error} />
          {tools.data && tools.data.length === 0 && (
            <p className="text-sm text-muted-foreground">No tools are available yet.</p>
          )}
          {tools.data && tools.data.length > 0 && (
            <ToolPicker
              tools={tools.data}
              selected={resolvedTools}
              orgId={orgId}
              integrations={{
                items: integrations.data?.items,
                loading: needsIntegrations && integrations.isPending && !integrations.error,
                error: integrations.error,
              }}
              onChange={(next) => set("tools", next)}
            />
          )}
          {errors.tools && (
            <p role="alert" className="text-sm text-danger">
              {errors.tools}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Approvals are not available yet. Until they are, a tool marked as needing approval is
            skipped when the agent tries to use it
            {anyApproval ? " (you have chosen at least one)" : ""}.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Limits</CardTitle>
          <CardDescription>
            Each run stops when it reaches any of these. The platform also enforces its own
            maximums.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <Field
            id="limit-iterations"
            label="Model calls per run"
            inputMode="numeric"
            value={values.maxIterations}
            onChange={text("maxIterations")}
            error={errors.maxIterations}
            hint={`${LIMITS.maxIterations.min} to ${LIMITS.maxIterations.max}`}
          />
          <Field
            id="limit-tool-calls"
            label="Tool calls per run"
            inputMode="numeric"
            value={values.maxToolCalls}
            onChange={text("maxToolCalls")}
            error={errors.maxToolCalls}
            hint={`${LIMITS.maxToolCalls.min} to ${LIMITS.maxToolCalls.max}`}
          />
          <Field
            id="limit-timeout"
            label="Time limit (seconds)"
            inputMode="numeric"
            value={values.timeoutSeconds}
            onChange={text("timeoutSeconds")}
            error={errors.timeoutSeconds}
            hint={`${LIMITS.timeoutSeconds.min} to ${LIMITS.timeoutSeconds.max}`}
          />
          <Field
            id="limit-tokens"
            label="Token limit per run"
            inputMode="numeric"
            value={values.maxTotalTokens}
            onChange={text("maxTotalTokens")}
            error={errors.maxTotalTokens}
            hint={`${LIMITS.maxTotalTokens.min.toLocaleString("en")} to ${LIMITS.maxTotalTokens.max.toLocaleString("en")}`}
          />
          <Field
            id="limit-cost"
            label="Cost budget in US dollars (optional)"
            inputMode="decimal"
            value={values.costBudget}
            onChange={text("costBudget")}
            error={errors.costBudget}
            hint="Needs model prices set on the server, or runs are refused."
          />
          <Field
            id="limit-output"
            label="Maximum reply length in tokens (optional)"
            inputMode="numeric"
            value={values.maxOutputTokens}
            onChange={text("maxOutputTokens")}
            error={errors.maxOutputTokens}
            hint="Leave empty to use the model's default."
            className="sm:col-span-2"
          />
        </CardContent>
      </Card>

      {mode === "edit" && (
        <Card>
          <CardHeader>
            <CardTitle>Change note</CardTitle>
            <CardDescription>Shown in the version history.</CardDescription>
          </CardHeader>
          <CardContent>
            <Field
              id="change-note"
              label="What changed? (optional)"
              value={values.changeNote}
              onChange={text("changeNote")}
              error={errors.changeNote}
            />
          </CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={submitting}>
          {submitting ? submittingLabel : submitLabel}
        </Button>
        <Link href={cancelHref} className={buttonVariants({ variant: "ghost" })}>
          Cancel
        </Link>
      </div>
    </form>
  );
}
