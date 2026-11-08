"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { useDeleteOrganization, useRenameOrganization } from "@/lib/api/queries";
import { canDeleteOrganization, canUpdateOrganization } from "@/lib/permissions";
import { validateOrganizationName } from "@/lib/validation";

function RenameForm({ orgId, currentName }: { orgId: string; currentName: string }) {
  const rename = useRenameOrganization(orgId);
  const [name, setName] = useState(currentName);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    const validation = validateOrganizationName(name);
    setError(validation);
    if (validation) return;
    rename.mutate(name.trim(), { onSuccess: () => setSaved(true) });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Organization name</CardTitle>
        <CardDescription>Shown to everyone in the organization.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          <ErrorNotice error={rename.error} />
          {saved && <Alert variant="success">Name updated.</Alert>}
          <Field
            id="org-name"
            label="Name"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
              setSaved(false);
            }}
            error={error}
          />
          <Button
            type="submit"
            disabled={rename.isPending || name.trim() === currentName}
            className="w-fit"
          >
            {rename.isPending ? "Saving…" : "Save"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function DangerZone({ orgId, orgName }: { orgId: string; orgName: string }) {
  const router = useRouter();
  const remove = useDeleteOrganization(orgId);
  const [confirmation, setConfirmation] = useState("");

  return (
    <Card className="border-danger/40">
      <CardHeader>
        <CardTitle>Delete organization</CardTitle>
        <CardDescription>
          Permanently deletes the organization, its members, invitations and everything else in it.
          This cannot be undone.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            remove.mutate(undefined, { onSuccess: () => router.replace("/dashboard") });
          }}
        >
          <ErrorNotice error={remove.error} />
          <Field
            id="confirm-delete"
            label={`Type "${orgName}" to confirm`}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            autoComplete="off"
          />
          <Button
            type="submit"
            variant="outline"
            className="w-fit border-danger/60 text-danger hover:bg-danger/10"
            disabled={confirmation !== orgName || remove.isPending}
          >
            {remove.isPending ? "Deleting…" : "Delete this organization"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function OrgOverview() {
  const org = useCurrentOrg();
  return (
    <div className="max-w-2xl space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Details</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-3 text-sm">
            <dt className="text-muted-foreground">URL name</dt>
            <dd>{org.slug}</dd>
            <dt className="text-muted-foreground">Created</dt>
            <dd>{new Date(org.created_at).toLocaleDateString()}</dd>
            <dt className="text-muted-foreground">Organization ID</dt>
            <dd className="break-all font-mono text-xs">{org.id}</dd>
          </dl>
        </CardContent>
      </Card>
      {canUpdateOrganization(org.role) && <RenameForm orgId={org.id} currentName={org.name} />}
      {canDeleteOrganization(org.role) && <DangerZone orgId={org.id} orgName={org.name} />}
    </div>
  );
}
