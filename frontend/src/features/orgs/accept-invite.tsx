"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/features/auth/auth-provider";
import { ApiError } from "@/lib/api-client";
import { useAcceptInvitation } from "@/lib/api/queries";
import { ROLE_LABELS } from "@/lib/permissions";

export function AcceptInvite() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { user, signOut } = useAuth();
  const accept = useAcceptInvitation();

  if (accept.data) {
    const { organization, role } = accept.data;
    return (
      <Card className="mx-auto max-w-lg">
        <CardHeader>
          <CardTitle className="text-xl">Welcome to {organization.name}</CardTitle>
          <CardDescription>You joined as {ROLE_LABELS[role]}.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href={`/orgs/${organization.id}`} className={buttonVariants()}>
            Open {organization.name}
          </Link>
        </CardContent>
      </Card>
    );
  }

  const mismatch =
    accept.error instanceof ApiError && accept.error.code === "invitation_email_mismatch";

  return (
    <Card className="mx-auto max-w-lg">
      <CardHeader>
        <CardTitle className="text-xl">You have been invited</CardTitle>
        <CardDescription>
          You are signed in as <strong>{user?.email}</strong>. Accept the invitation to join the
          organization.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {mismatch ? (
          <Alert variant="error" className="space-y-3">
            <p>
              This invitation was sent to a different email address. Sign out and sign in with the
              address that was invited.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                await signOut();
                router.replace(`/login?next=${encodeURIComponent(`/invite/${token}`)}`);
              }}
            >
              Sign out and switch account
            </Button>
          </Alert>
        ) : (
          <ErrorNotice error={accept.error} />
        )}
        <Button onClick={() => accept.mutate(token)} disabled={accept.isPending}>
          {accept.isPending ? "Joining…" : "Accept invitation"}
        </Button>
      </CardContent>
    </Card>
  );
}
