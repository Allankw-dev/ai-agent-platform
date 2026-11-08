"use client";

import { useParams, useRouter } from "next/navigation";

import { Select } from "@/components/ui/select";
import { useOrganizations } from "@/lib/api/queries";

const NEW_ORG = "__new";

export function OrgSwitcher() {
  const router = useRouter();
  const params = useParams<{ orgId?: string }>();
  const { data } = useOrganizations();
  const organizations = data?.items ?? [];

  return (
    <Select
      aria-label="Organization"
      className="max-w-48"
      value={params.orgId ?? ""}
      onChange={(event) => {
        const value = event.target.value;
        if (value === NEW_ORG) router.push("/orgs/new");
        else if (value) router.push(`/orgs/${value}`);
      }}
    >
      <option value="" disabled>
        {organizations.length ? "Select organization" : "No organizations"}
      </option>
      {organizations.map((org) => (
        <option key={org.id} value={org.id}>
          {org.name}
        </option>
      ))}
      <option value={NEW_ORG}>+ Create organization</option>
    </Select>
  );
}
