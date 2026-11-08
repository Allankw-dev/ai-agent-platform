import type { Metadata } from "next";

import { CreateOrgForm } from "@/features/orgs/create-org-form";

export const metadata: Metadata = { title: "New organization" };

export default function Page() {
  return <CreateOrgForm />;
}
