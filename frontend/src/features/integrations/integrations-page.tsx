"use client";

import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { IntegrationCard } from "@/features/integrations/integration-card";
import { IntegrationForm } from "@/features/integrations/integration-form";
import { toConfig } from "@/features/integrations/integration-form-model";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { useCreateIntegration, useIntegrations, useSaveSecret } from "@/lib/api/queries";
import { canManageIntegrations, canViewIntegrations } from "@/lib/permissions";

const PAGE_SIZE = 50;

export function IntegrationsPage() {
  const org = useCurrentOrg();
  if (!canViewIntegrations(org.role)) {
    return (
      <Card className="max-w-2xl">
        <CardContent className="p-6 text-sm text-muted-foreground">
          Only owners, admins and developers can see integrations.
        </CardContent>
      </Card>
    );
  }
  return <IntegrationsList orgId={org.id} mayManage={canManageIntegrations(org.role)} />;
}

function IntegrationsList({ orgId, mayManage }: { orgId: string; mayManage: boolean }) {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const integrations = useIntegrations(orgId, limit);
  const create = useCreateIntegration(orgId);
  const saveSecret = useSaveSecret(orgId);

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Integrations</h2>
          <p className="text-sm text-muted-foreground">
            Connections to outside services that agents can use. Secrets are stored encrypted and
            can be replaced or removed, but never shown again.
          </p>
        </div>
        {mayManage && !adding && (
          <Button
            onClick={() => {
              create.reset();
              setNotice(null);
              setAdding(true);
            }}
          >
            Add integration
          </Button>
        )}
      </div>

      {!mayManage && (
        <Alert variant="info">
          Only owners and admins can add or change integrations and their secrets.
        </Alert>
      )}
      {notice && <Alert variant="error">{notice}</Alert>}

      {adding && (
        <Card>
          <CardContent className="p-5">
            <IntegrationForm
              mode="create"
              pending={create.isPending || saveSecret.isPending}
              error={create.error}
              onCancel={() => setAdding(false)}
              onSubmit={(values) => {
                create.mutate(
                  { provider: values.provider, name: values.name, config: toConfig(values) },
                  {
                    onSuccess: (created) => {
                      const secret = values.secret.trim();
                      if (!secret) {
                        setAdding(false);
                        return;
                      }
                      saveSecret.mutate(
                        { integrationId: created.id, secret },
                        {
                          onSuccess: () => setAdding(false),
                          onError: (error) => {
                            // The integration exists; only its secret failed to save.
                            setAdding(false);
                            setNotice(
                              `“${created.name}” was added, but its secret was not saved: ${error.message} Add the secret from the list below.`,
                            );
                          },
                        },
                      );
                    },
                  },
                );
              }}
            />
          </CardContent>
        </Card>
      )}

      <ErrorNotice error={integrations.error} />
      {integrations.isPending && !integrations.error && <Spinner label="Loading integrations" />}

      {integrations.data && integrations.data.items.length === 0 && !adding && (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            {mayManage
              ? "No integrations yet. Add one to let agents use an outside service."
              : "No integrations yet. An owner or admin can add them."}
          </CardContent>
        </Card>
      )}

      {integrations.data && integrations.data.items.length > 0 && (
        <ul className="space-y-3">
          {integrations.data.items.map((integration) => (
            <li key={integration.id}>
              <IntegrationCard orgId={orgId} integration={integration} mayManage={mayManage} />
            </li>
          ))}
        </ul>
      )}

      {integrations.data && integrations.data.total > integrations.data.items.length && (
        <Button variant="outline" size="sm" onClick={() => setLimit((value) => value + PAGE_SIZE)}>
          Show more
        </Button>
      )}
    </div>
  );
}
