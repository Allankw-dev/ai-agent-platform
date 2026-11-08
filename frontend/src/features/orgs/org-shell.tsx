"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ErrorNotice } from "@/components/error-notice";
import { OrgProvider } from "@/features/orgs/org-context";
import { ApiError } from "@/lib/api-client";
import { useOrganization } from "@/lib/api/queries";
import { ROLE_LABELS } from "@/lib/permissions";
import { cn } from "@/lib/utils";

export function OrgShell({ children }: { children: React.ReactNode }) {
  const { orgId } = useParams<{ orgId: string }>();
  const pathname = usePathname();
  const { data: org, error, isPending } = useOrganization(orgId);

  if (isPending && !error) return <Spinner label="Loading organization" />;

  if (error instanceof ApiError && error.status === 404) {
    return (
      <Card className="mx-auto max-w-lg text-center">
        <CardHeader>
          <CardTitle>Organization not found</CardTitle>
          <CardDescription>
            It may have been deleted, or you may not be a member of it.
          </CardDescription>
          <div className="pt-4">
            <Link href="/dashboard" className={buttonVariants({ variant: "outline" })}>
              Back to your organizations
            </Link>
          </div>
        </CardHeader>
      </Card>
    );
  }
  if (error || !org) return <ErrorNotice error={error} />;

  const tabs = [
    { href: `/orgs/${org.id}`, label: "Overview" },
    { href: `/orgs/${org.id}/members`, label: "Members" },
  ];

  return (
    <OrgProvider value={org}>
      <div className="space-y-8">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{org.name}</h1>
            <Badge variant={org.role === "owner" ? "default" : "muted"}>
              {ROLE_LABELS[org.role]}
            </Badge>
          </div>
          <nav aria-label="Organization" className="flex gap-1 border-b border-border">
            {tabs.map((tab) => {
              const active = pathname === tab.href;
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
                    active
                      ? "border-accent text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
        </div>
        {children}
      </div>
    </OrgProvider>
  );
}
