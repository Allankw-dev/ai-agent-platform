"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { AuthCard } from "@/features/auth/auth-card";
import { useAuth } from "@/features/auth/auth-provider";
import { describeAuthError } from "@/lib/auth-errors";
import { getSupabase } from "@/lib/supabase";
import {
  MIN_PASSWORD_LENGTH,
  validateNewPassword,
  validatePasswordConfirmation,
} from "@/lib/validation";

export function ResetPasswordForm() {
  const router = useRouter();
  const { status } = useAuth();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
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
      setDone(true);
    } catch (caught) {
      setFormError(describeAuthError(caught));
    } finally {
      setPending(false);
    }
  }

  if (status === "loading") {
    return (
      <AuthCard title="Choose a new password">
        <Spinner />
      </AuthCard>
    );
  }

  // The reset link signs you in; without a session the link was invalid, expired or already used.
  if (status === "unauthenticated") {
    return (
      <AuthCard
        title="This link is not valid"
        description="The reset link has expired or was already used."
      >
        <Link href="/forgot-password" className="text-sm text-accent hover:underline">
          Request a new link
        </Link>
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard title="Password updated" description="You can now use your new password.">
        <Button onClick={() => router.replace("/dashboard")}>Go to dashboard</Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Choose a new password">
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {formError && <Alert variant="error">{formError}</Alert>}
        <Field
          id="password"
          label="New password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
        />
        <Field
          id="confirmation"
          label="Repeat new password"
          type="password"
          autoComplete="new-password"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          error={errors.confirmation}
        />
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? "Saving…" : "Update password"}
        </Button>
      </form>
    </AuthCard>
  );
}
