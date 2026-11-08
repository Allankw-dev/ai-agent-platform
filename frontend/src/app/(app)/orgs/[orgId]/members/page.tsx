import { Suspense } from "react";
import type { Metadata } from "next";

import { OrgMembersPage } from "@/features/orgs/org-members-page";

export const metadata: Metadata = { title: "Members" };

export default function Page() {
  return (
    <Suspense>
      <OrgMembersPage />
    </Suspense>
  );
}
