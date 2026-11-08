"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ErrorNotice } from "@/components/error-notice";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { ApiError } from "@/lib/api-client";
import { useCreateOrganization } from "@/lib/api/queries";
import { validateOrganizationName, validateSlug } from "@/lib/validation";

export function CreateOrgForm() {
  const router = useRouter();
  const create = useCreateOrganization();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [errors, setErrors] = useState<{ name?: string | null; slug?: string | null }>({});

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    const nextErrors = { name: validateOrganizationName(name), slug: validateSlug(slug) };
    setErrors(nextErrors);
    if (nextErrors.name || nextErrors.slug) return;

    create.mutate(
      { name: name.trim(), slug: slug.trim() || undefined },
      { onSuccess: (org) => router.push(`/orgs/${org.id}`) },
    );
  }

  const slugTaken = create.error instanceof ApiError && create.error.code === "slug_taken";

  return (
    <Card className="mx-auto max-w-lg">
      <CardHeader>
        <CardTitle className="text-xl">Create an organization</CardTitle>
        <CardDescription>
          You will be its owner and can invite your team afterwards.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="space-y-4">
          {!slugTaken && <ErrorNotice error={create.error} />}
          <Field
            id="name"
            label="Organization name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            error={errors.name}
            autoComplete="organization"
          />
          <Field
            id="slug"
            label="URL name (optional)"
            hint="Lowercase letters, numbers and hyphens. Leave empty to generate one."
            value={slug}
            onChange={(event) => setSlug(event.target.value.toLowerCase())}
            error={errors.slug ?? (slugTaken ? "That URL name is already in use." : null)}
          />
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create organization"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
