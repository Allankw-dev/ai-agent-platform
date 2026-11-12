import { Suspense } from "react";

import { Spinner } from "@/components/ui/spinner";
import { OrgShell } from "@/features/orgs/org-shell";

export default function OrgLayout({ children }: { children: React.ReactNode }) {
  return (
    // OrgShell reads the [orgId] route param, which is only known at request time, so it renders
    // inside Suspense. The fallback is what navigation shows straight away while it resolves.
    <Suspense fallback={<Spinner label="Loading organization" />}>
      <OrgShell>{children}</OrgShell>
    </Suspense>
  );
}
