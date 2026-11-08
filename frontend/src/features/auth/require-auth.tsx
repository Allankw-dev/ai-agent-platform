"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "@/features/auth/auth-provider";

/** Renders its children only for signed-in users; everyone else is sent to the sign-in page. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status, configured } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "unauthenticated" && configured) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, configured, pathname, router]);

  if (!configured) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <Alert variant="error">
          Sign-in is not configured. Set NEXT_PUBLIC_SUPABASE_URL and
          NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY, then restart.
        </Alert>
      </div>
    );
  }
  if (status !== "authenticated") {
    return (
      <div className="grid min-h-64 place-items-center p-8">
        <Spinner />
      </div>
    );
  }
  return <>{children}</>;
}
