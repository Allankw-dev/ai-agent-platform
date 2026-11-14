import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { RunsListPage } from "@/features/runs/runs-list-page";

export const metadata: Metadata = { title: "Runs" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading runs" />}>
      <RunsListPage />
    </Suspense>
  );
}
