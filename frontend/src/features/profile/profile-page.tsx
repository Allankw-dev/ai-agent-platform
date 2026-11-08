"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/features/auth/auth-provider";
import { useMe } from "@/lib/api/queries";
import { describeAuthError } from "@/lib/auth-errors";
import { getSupabase } from "@/lib/supabase";
import { validateNewPassword, validatePasswordConfirmation } from "@/lib/validation";

function ChangePassword() {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSaved(false);
    setFormError(null);
    const nextErrors = {
      password: validateNewPassword(password),
      confirmation: validatePasswordConfirmation(password, confirmation),
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    setPending(true);
    try {
      const { error } = await getSupabase().auth.updateUser({ password });
      if (error) {
        setFormError(describeAuthError(error));
        return;
      }
      setSaved(true);
      setPassword("");
      setConfirmation("");
    } catch (caught) {
      setFormError(describeAuthError(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>Choose a new password for your account.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          {formError && <Alert variant="error">{formError}</Alert>}
          {saved && <Alert variant="success">Password updated.</Alert>}
          <Field
            id="new-password"
            label="New password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={errors.password}
          />
          <Field
            id="confirm-new-password"
            label="Repeat new password"
            type="password"
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            error={errors.confirmation}
          />
          <Button type="submit" disabled={pending} className="w-fit">
            {pending ? "Saving…" : "Update password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function ProfilePage() {
  const router = useRouter();
  const { signOut } = useAuth();
  const { data, error, isPending } = useMe();

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Your profile</h1>
      <Card>
        <CardHeader>
          <CardTitle>Account</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ErrorNotice error={error} />
          {isPending && !error && <Spinner label="Loading profile" />}
          {data && (
            <dl className="grid grid-cols-[8rem_1fr] gap-y-3 text-sm">
              <dt className="text-muted-foreground">Email</dt>
              <dd>{data.email}</dd>
              <dt className="text-muted-foreground">Member since</dt>
              <dd>{new Date(data.created_at).toLocaleDateString()}</dd>
              <dt className="text-muted-foreground">User ID</dt>
              <dd className="break-all font-mono text-xs">{data.id}</dd>
            </dl>
          )}
          <Button
            variant="outline"
            onClick={async () => {
              await signOut();
              router.replace("/");
            }}
          >
            Sign out
          </Button>
        </CardContent>
      </Card>
      <ChangePassword />
    </div>
  );
}
