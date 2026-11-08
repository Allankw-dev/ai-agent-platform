"use client";

import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useCreateInvitation, useInvitations, useRevokeInvitation } from "@/lib/api/queries";
import type { InvitationCreated, InvitationStatus, OrgRole } from "@/lib/api/types";
import { ROLE_LABELS, invitableRoles } from "@/lib/permissions";
import { validateEmail } from "@/lib/validation";

const PAGE_SIZE = 50;

const STATUS_VARIANT: Record<InvitationStatus, "accent" | "success" | "muted"> = {
  pending: "accent",
  accepted: "success",
  expired: "muted",
  revoked: "muted",
};

function InviteLink({ invitation }: { invitation: InvitationCreated }) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(invitation.invite_url);
      setCopied(true);
      setCopyFailed(false);
    } catch {
      setCopyFailed(true);
    }
  }

  return (
    <Alert variant="success" className="space-y-3">
      <p>
        Invitation created for <strong>{invitation.email}</strong>. Send them this link. It is shown
        only once.
      </p>
      <div className="flex gap-2">
        <Input
          readOnly
          aria-label="Invitation link"
          value={invitation.invite_url}
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button variant="outline" onClick={copy}>
          {copied ? "Copied" : "Copy link"}
        </Button>
      </div>
      {copyFailed && (
        <p className="text-xs">Copying failed. Select the link and copy it by hand.</p>
      )}
      <p className="text-xs text-muted-foreground">
        They must sign in with {invitation.email} to accept it.
      </p>
    </Alert>
  );
}

export function InvitationsPanel({ orgId, myRole }: { orgId: string; myRole: OrgRole }) {
  const roles = invitableRoles(myRole);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>(roles.at(-1) ?? "member");
  const [emailError, setEmailError] = useState<string | null>(null);
  const [created, setCreated] = useState<InvitationCreated | null>(null);

  const invitations = useInvitations(orgId, limit, true);
  const create = useCreateInvitation(orgId);
  const revoke = useRevokeInvitation(orgId);

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setCreated(null);
    const validation = validateEmail(email);
    setEmailError(validation);
    if (validation) return;
    create.mutate(
      { email: email.trim(), role },
      {
        onSuccess: (invitation) => {
          setCreated(invitation);
          setEmail("");
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Invitations</CardTitle>
        <CardDescription>
          Invite people by email. You get a one-time link to send them; invitations expire after 7
          days.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <form onSubmit={onSubmit} noValidate className="flex flex-wrap items-start gap-3">
          <Field
            id="invite-email"
            label="Email"
            type="email"
            className="min-w-64 flex-1"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            error={emailError}
          />
          <div className="space-y-1.5">
            <label htmlFor="invite-role" className="text-sm font-medium">
              Role
            </label>
            <Select
              id="invite-role"
              className="block"
              value={role}
              onChange={(event) => setRole(event.target.value as OrgRole)}
            >
              {roles.map((value) => (
                <option key={value} value={value}>
                  {ROLE_LABELS[value]}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" className="mt-[1.625rem]" disabled={create.isPending}>
            {create.isPending ? "Inviting…" : "Create invitation"}
          </Button>
        </form>

        <ErrorNotice error={create.error ?? revoke.error ?? invitations.error} />
        {created && <InviteLink invitation={created} />}

        {invitations.isPending && !invitations.error && <Spinner label="Loading invitations" />}
        {invitations.data && invitations.data.items.length === 0 && (
          <p className="text-sm text-muted-foreground">No invitations yet.</p>
        )}
        {invitations.data && invitations.data.items.length > 0 && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {invitations.data.items.map((invitation) => (
              <li
                key={invitation.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{invitation.email}</p>
                  <p className="text-xs text-muted-foreground">
                    {ROLE_LABELS[invitation.role]} · expires{" "}
                    {new Date(invitation.expires_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={STATUS_VARIANT[invitation.status]}>{invitation.status}</Badge>
                  {invitation.status === "pending" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Revoke invitation for ${invitation.email}`}
                      disabled={revoke.isPending && revoke.variables === invitation.id}
                      onClick={() => revoke.mutate(invitation.id)}
                    >
                      Revoke
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {invitations.data && invitations.data.total > invitations.data.items.length && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setLimit((value) => value + PAGE_SIZE)}
          >
            Show more
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
