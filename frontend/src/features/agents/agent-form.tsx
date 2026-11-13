"use client";

import { useState } from "react";
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
  validateAgentForm,
  type AgentFormValues,
  type ToolSelection,
} from "@/features/agents/agent-form-model";
import { useTools } from "@/lib/api/queries";
import type { ToolInfo } from "@/lib/api/types";

type Props = {
  mode: "create" | "edit";
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

function ToolPicker({
  tools,
  selected,
  onChange,
}: {
  tools: ToolInfo[];
  selected: ToolSelection[];
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
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [
                          ...selected,
                          { toolKey: tool.key, requiresApproval: tool.is_sensitive, config: {} },
                        ]
                      : selected.filter((entry) => entry.toolKey !== tool.key),
                  )
                }
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
  const [values, setValues] = useState<AgentFormValues>(initial);
  const [errors, setErrors] = useState<ReturnType<typeof validateAgentForm>>({});

  const set = <K extends keyof AgentFormValues>(key: K, value: AgentFormValues[K]) =>
    setValues((current) => ({ ...current, [key]: value }));
  const text =
    (key: keyof AgentFormValues & string) =>
    (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      set(key, event.target.value as never);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found = validateAgentForm(values, mode);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    onSubmit(values);
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
              selected={values.tools}
              onChange={(next) => set("tools", next)}
            />
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
