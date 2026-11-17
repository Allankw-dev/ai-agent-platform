"use client";

import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { IntegrationForm } from "@/features/integrations/integration-form";
import {
  PROVIDER_LABELS,
  describeSettings,
  fromIntegration,
  toConfig,
} from "@/features/integrations/integration-form-model";
import {
  useDeleteIntegration,
  useRemoveSecret,
  useSaveSecret,
  useUpdateIntegration,
} from "@/lib/api/queries";
import type { Integration } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

type Mode = "idle" | "edit" | "secret" | "remove-secret" | "delete";

const DANGER = "border-danger/60 text-danger hover:bg-danger/10";

function StatusBadge({ status }: { status: Integration["status"] }) {
  if (status === "active") return <Badge variant="success">Active</Badge>;
  if (status === "error") return <Badge variant="danger">Error</Badge>;
  return <Badge variant="muted">Disabled</Badge>;
}

export function IntegrationCard({
  orgId,
  integration,
  mayManage,
}: {
  orgId: string;
  integration: Integration;
  mayManage: boolean;
}) {
  const [mode, setMode] = useState<Mode>("idle");
  const [secret, setSecret] = useState("");
  const update = useUpdateIntegration(orgId, integration.id);
  const saveSecret = useSaveSecret(orgId);
  const removeSecret = useRemoveSecret(orgId, integration.id);
  const remove = useDeleteIntegration(orgId, integration.id);

  const busy =
    update.isPending || saveSecret.isPending || removeSecret.isPending || remove.isPending;
  const supported = integration.provider === "http" || integration.provider === "slack";

  function resetErrors() {
    update.reset();
    saveSecret.reset();
    removeSecret.reset();
    remove.reset();
  }

  function go(next: Mode) {
    resetErrors();
    setSecret("");
    setMode(next);
  }

  function submitSecret() {
    const value = secret.trim();
    if (!value) return;
    saveSecret.mutate(
      { integrationId: integration.id, secret: value },
      {
        // Whatever happens, the typed secret does not stay in memory or on screen.
        onSettled: () => setSecret(""),
        onSuccess: () => setMode("idle"),
      },
    );
  }

  const when = integration.credential_updated_at
    ? formatDateTime(integration.credential_updated_at)
    : "";
  const by = integration.credential_set_by_name ? ` by ${integration.credential_set_by_name}` : "";

  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-semibold">{integration.name}</h3>
              <Badge variant="accent">{PROVIDER_LABELS[integration.provider]}</Badge>
              <StatusBadge status={integration.status} />
            </div>
            <p className="text-sm text-muted-foreground">{describeSettings(integration)}</p>
            <p className="text-sm text-muted-foreground">
              {integration.has_credential
                ? `Secret saved${by}${when ? ` on ${when}` : ""}. It cannot be shown again.`
                : "No secret saved."}
            </p>
          </div>

          {mayManage && mode === "idle" && supported && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                aria-label={`${integration.has_credential ? "Replace" : "Add"} secret for ${integration.name}`}
                onClick={() => go("secret")}
              >
                {integration.has_credential ? "Replace secret" : "Add secret"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Edit settings of ${integration.name}`}
                onClick={() => go("edit")}
              >
                Edit
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`${integration.status === "active" ? "Disable" : "Enable"} ${integration.name}`}
                disabled={busy}
                onClick={() =>
                  update.mutate({ status: integration.status === "active" ? "disabled" : "active" })
                }
              >
                {integration.status === "active" ? "Disable" : "Enable"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Delete ${integration.name}`}
                onClick={() => go("delete")}
              >
                Delete
              </Button>
            </div>
          )}
        </div>

        {mode === "edit" && (
          <IntegrationForm
            mode="edit"
            initial={fromIntegration(integration)}
            pending={update.isPending}
            error={update.error}
            onCancel={() => go("idle")}
            onSubmit={(values) =>
              update.mutate(
                { name: values.name, config: toConfig(values) },
                { onSuccess: () => setMode("idle") },
              )
            }
          />
        )}

        {mode === "secret" && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              submitSecret();
            }}
          >
            <Field
              id={`secret-${integration.id}`}
              type="password"
              autoComplete="new-password"
              label={integration.has_credential ? "New secret" : "Secret"}
              hint="It is encrypted before it is stored and can never be shown again."
              value={secret}
              onChange={(event) => setSecret(event.target.value)}
            />
            <ErrorNotice error={saveSecret.error} />
            <div className="flex flex-wrap gap-2">
              <Button type="submit" disabled={saveSecret.isPending || !secret.trim()}>
                {saveSecret.isPending ? "Saving…" : "Save secret"}
              </Button>
              <Button type="button" variant="ghost" onClick={() => go("idle")}>
                Cancel
              </Button>
              {integration.has_credential && (
                <Button
                  type="button"
                  variant="outline"
                  className={DANGER}
                  onClick={() => go("remove-secret")}
                >
                  Remove secret
                </Button>
              )}
            </div>
          </form>
        )}

        {mode === "remove-secret" && (
          <div className="space-y-3">
            <p className="text-sm">
              Remove the saved secret? Agents will not be able to use this integration until a new
              one is saved.
            </p>
            <ErrorNotice error={removeSecret.error} />
            <div className="flex gap-2">
              <Button
                variant="outline"
                className={DANGER}
                disabled={removeSecret.isPending}
                onClick={() => removeSecret.mutate(undefined, { onSuccess: () => setMode("idle") })}
              >
                Confirm remove secret
              </Button>
              <Button variant="ghost" onClick={() => go("idle")}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {mode === "delete" && (
          <div className="space-y-3">
            <p className="text-sm">
              Delete “{integration.name}” and its secret? This cannot be undone.
            </p>
            <ErrorNotice error={remove.error} />
            <div className="flex gap-2">
              <Button
                variant="outline"
                className={DANGER}
                disabled={remove.isPending}
                onClick={() => remove.mutate()}
              >
                Confirm delete
              </Button>
              <Button variant="ghost" onClick={() => go("idle")}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {mode === "idle" && <ErrorNotice error={update.error ?? removeSecret.error} />}
      </CardContent>
    </Card>
  );
}
