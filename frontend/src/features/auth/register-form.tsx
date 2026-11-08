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
import {
  MIN_PASSWORD_LENGTH,
  validateEmail,
  validateNewPassword,
  validatePasswordConfirmation,
} from "@/lib/validation";

const RESEND_COOLDOWN_SECONDS = 60;

export function RegisterForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const { status } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errors, setErrors] = useState<Record<string, string | null>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [resendMessage, setResendMessage] = useState<string | null>(null);

  useEffect(() => {
    if (status === "authenticated") router.replace(next ?? "/dashboard");
  }, [status, next, router]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const callbackUrl = () =>
    `${window.location.origin}/auth/callback?next=${encodeURIComponent(next ?? "/dashboard")}`;

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setFormError(null);
    const nextErrors = {
      email: validateEmail(email),
      password: validateNewPassword(password),
      confirmation: validatePasswordConfirmation(password, confirmation),
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;

    setPending(true);
    try {
      const { data, error } = await getSupabase().auth.signUp({
        email: email.trim(),
        password,
        options: { emailRedirectTo: callbackUrl() },
      });
      if (error) {
        setFormError(describeAuthError(error));
        setPending(false);
        return;
      }
      if (data.session) {
        // Email confirmation is switched off for this project: the user is already signed in.
        router.replace(next ?? "/dashboard");
        return;
      }
      setSentTo(email.trim());
      setCooldown(RESEND_COOLDOWN_SECONDS);
      setPending(false);
    } catch (error) {
      setFormError(describeAuthError(error));
      setPending(false);
    }
  }

  async function resend() {
    if (!sentTo) return;
    setResendMessage(null);
    try {
      const { error } = await getSupabase().auth.resend({
        type: "signup",
        email: sentTo,
        options: { emailRedirectTo: callbackUrl() },
      });
      setResendMessage(error ? describeAuthError(error) : "We sent the email again.");
      if (!error) setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (error) {
      setResendMessage(describeAuthError(error));
    }
  }

  if (sentTo) {
    return (
      <AuthCard
        title="Check your email"
        description={`We sent a confirmation link to ${sentTo}. Open it to finish creating your account.`}
        footer={
          <p>
            Already confirmed?{" "}
            <Link href="/login" className="text-accent hover:underline">
              Sign in
            </Link>
          </p>
        }
      >
        {resendMessage && <Alert>{resendMessage}</Alert>}
        <p className="text-sm text-muted-foreground">
          The email can take a few minutes and may land in spam. Open the link in this same browser.
        </p>
        <Button variant="outline" onClick={resend} disabled={cooldown > 0}>
          {cooldown > 0 ? `Resend email in ${cooldown}s` : "Resend email"}
        </Button>
      </AuthCard>
    );
  }

  const query = next ? `?next=${encodeURIComponent(next)}` : "";

  return (
    <AuthCard
      title="Create your account"
      description="Start building agents that work under your control."
      footer={
        <p>
          Already have an account?{" "}
          <Link href={`/login${query}`} className="text-accent hover:underline">
            Sign in
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
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
        />
        <Field
          id="confirmation"
          label="Repeat password"
          type="password"
          autoComplete="new-password"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          error={errors.confirmation}
        />
        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthCard>
  );
}
