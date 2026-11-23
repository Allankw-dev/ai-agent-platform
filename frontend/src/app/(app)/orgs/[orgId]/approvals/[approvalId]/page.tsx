import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { ApprovalPage } from "@/features/approvals/approval-page";

export const metadata: Metadata = { title: "Approval" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading approval" />}>
      <ApprovalPage />
    </Suspense>
  );
}
