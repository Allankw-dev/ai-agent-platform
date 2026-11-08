import { Suspense } from "react";

import { OrgShell } from "@/features/orgs/org-shell";

export default function OrgLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense>
      <OrgShell>{children}</OrgShell>
    </Suspense>
  );
}
