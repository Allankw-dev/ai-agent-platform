"use client";

import Link from "next/link";

import { ErrorNotice } from "@/components/error-notice";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { useOrganizations } from "@/lib/api/queries";
import { ROLE_LABELS } from "@/lib/permissions";

export function Dashboard() {
  const { data, isPending, error } = useOrganizations();

  if (isPending && !error) return <Spinner label="Loading your organizations" />;
  if (error) return <ErrorNotice error={error} />;

  const organizations = data.items;

  if (organizations.length === 0) {
    return (
      <Card className="mx-auto max-w-xl text-center">
        <CardHeader>
          <CardTitle className="text-xl">Create your first organization</CardTitle>
          <CardDescription>
            An organization is your team&apos;s workspace. Agents, integrations and members all live
            inside one.
          </CardDescription>
          <div className="pt-4">
            <Link href="/orgs/new" className={buttonVariants()}>
              Create organization
            </Link>
          </div>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Your organizations</h1>
        <Link href="/orgs/new" className={buttonVariants({ variant: "outline", size: "sm" })}>
          Create organization
        </Link>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {organizations.map((org) => (
          <li key={org.id}>
            <Link
              href={`/orgs/${org.id}`}
              className="block rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Card className="transition-colors hover:border-primary/60">
                <CardHeader>
                  <CardTitle>{org.name}</CardTitle>
                  <CardDescription>{org.slug}</CardDescription>
                  <div className="pt-2">
                    <Badge variant={org.role === "owner" ? "default" : "muted"}>
                      {ROLE_LABELS[org.role]}
                    </Badge>
                  </div>
                </CardHeader>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
