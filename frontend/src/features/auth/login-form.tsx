"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { AuthCard } from "@/features/auth/auth-card";
import { useAuth } from "@/features/auth/auth-provider";
import { describeAuthError } from "@/lib/auth-errors";
import { safeNext } from "@/lib/safe-redirect";
import { getSupabase } from "@/lib/supabase";
import { validateEmail } from "@/lib/validation";

export function LoginForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const { status } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string | null; password?: string | null }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // Someone who is already signed in has no reason to see this page.
  useEffect(() => {
    if (status === "authenticated") router.replace(next ?? "/dashboard");
  }, [status, next, router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setFormError(null);
    const nextErrors = {
      email: validateEmail(email),
      password: password ? null : "Enter your password.",
    };
    setErrors(nextErrors);
    if (nextErrors.email || nextErrors.password) return;

    setPending(true);
    try {
      const { error } = await getSupabase().auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (error) {
        setFormError(describeAuthError(error));
        setPending(false);
        return;
      }
      router.replace(next ?? "/dashboard");
    } catch (error) {
      setFormError(describeAuthError(error));
      setPending(false);
    }
  }

  const query = next ? `?next=${encodeURIComponent(next)}` : "";

  return (
    <AuthCard
      title="Sign in"
      description="Welcome back. Sign in to manage your agents."
      footer={
        <p>
          New here?{" "}
          <Link href={`/register${query}`} className="text-accent hover:underline">
            Create an account
          </Link>
        </p>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        {formError && <Alert variant="error">{formError}</Alert>}
        <Field
          id="email"
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={errors.email}
        />
        <Field
          id="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
        />
        <div className="flex justify-end">
          <Link href="/forgot-password" className="text-sm text-accent hover:underline">
            Forgot your password?
          </Link>
        </div>
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthCard>
  );
}
