"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-provider";
import { OrgSwitcher } from "@/features/orgs/org-switcher";

export function AppHeader() {
  const router = useRouter();
  const { user, signOut } = useAuth();

  return (
    <header className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-6">
        <div className="flex items-center gap-4">
          <Link href="/dashboard" className="flex items-center gap-2 font-semibold">
            <span
              aria-hidden
              className="grid size-7 place-items-center rounded-md bg-gradient-to-br from-primary to-accent text-xs font-bold text-background"
            >
              A
            </span>
            <span className="hidden sm:inline">Agent Platform</span>
          </Link>
          <OrgSwitcher />
        </div>
        <nav aria-label="Account" className="flex items-center gap-2 text-sm">
          <Link
            href="/profile"
            className="hidden max-w-48 truncate text-muted-foreground hover:text-foreground sm:inline"
          >
            {user?.email}
          </Link>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              await signOut();
              router.replace("/");
            }}
          >
            Sign out
          </Button>
        </nav>
      </div>
    </header>
  );
}
