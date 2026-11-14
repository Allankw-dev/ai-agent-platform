import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { RunDetailPage } from "@/features/runs/run-detail-page";

export const metadata: Metadata = { title: "Run" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading run" />}>
      <RunDetailPage />
    </Suspense>
  );
}
