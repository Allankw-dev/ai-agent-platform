"use client";

import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-provider";

/** Sign in / Get started for visitors; a Dashboard link for people who are signed in. */
export function HeaderAuthLinks() {
  const { status } = useAuth();
  if (status === "loading") return <span aria-hidden className="h-9 w-40" />;
  if (status === "authenticated") {
    return (
      <Link href="/dashboard" className={buttonVariants({ size: "sm" })}>
        Dashboard
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <Link href="/login" className={buttonVariants({ size: "sm", variant: "ghost" })}>
        Sign in
      </Link>
      <Link href="/register" className={buttonVariants({ size: "sm" })}>
        Get started
      </Link>
    </div>
  );
}
