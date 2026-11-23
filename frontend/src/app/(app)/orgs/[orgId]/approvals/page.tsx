import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { ApprovalsPage } from "@/features/approvals/approvals-page";

export const metadata: Metadata = { title: "Approvals" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading approvals" />}>
      <ApprovalsPage />
    </Suspense>
  );
}
