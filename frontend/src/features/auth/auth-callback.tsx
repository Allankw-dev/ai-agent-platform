"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { AuthCard } from "@/features/auth/auth-card";
import { Spinner } from "@/components/ui/spinner";
import { safeNext } from "@/lib/safe-redirect";
import { getSupabase } from "@/lib/supabase";

/** Supabase reports problems (such as an expired link) in the query string or the URL fragment. */
function readProvidedError(query: URLSearchParams): string | null {
  const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return query.get("error_description") ?? fragment.get("error_description");
}

const NOT_VALID =
  "This link is not valid or has expired. If you already confirmed your email, you can sign in.";

/** Landing page for links in emails: confirms the code, signs the user in, then moves on. */
export function AuthCallback() {
  const router = useRouter();
  const params = useSearchParams();
  const started = useRef(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // The code can only be exchanged once, and development mode runs effects twice.
    if (started.current) return;
    started.current = true;

    const next = safeNext(params.get("next")) ?? "/dashboard";
    const code = params.get("code");

    async function finish() {
      const provided = readProvidedError(params);
      if (provided) return setError(provided.replace(/\+/g, " "));

      const supabase = getSupabase();
      if (code) {
        const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
        if (exchangeError) return setError(NOT_VALID);
        return router.replace(next);
      }
      const { data } = await supabase.auth.getSession();
      if (data.session) return router.replace(next);
      setError(NOT_VALID);
    }

    finish().catch(() => setError(NOT_VALID));
  }, [params, router]);

  if (error) {
    return (
      <AuthCard
        title="We could not sign you in"
        description={error}
        footer={
          <Link href="/login" className="text-accent hover:underline">
            Go to sign in
          </Link>
        }
      >
        <span />
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Signing you in">
      <Spinner label="Confirming" />
    </AuthCard>
  );
}
