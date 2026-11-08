import { Suspense } from "react";
import type { Metadata } from "next";

import { OrgOverview } from "@/features/orgs/org-overview";

export const metadata: Metadata = { title: "Organization" };

export default function Page() {
  return (
    <Suspense>
      <OrgOverview />
    </Suspense>
  );
}
