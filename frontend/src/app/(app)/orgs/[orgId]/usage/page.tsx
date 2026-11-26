import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { UsagePage } from "@/features/usage/usage-page";

export const metadata: Metadata = { title: "Usage" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading usage" />}>
      <UsagePage />
    </Suspense>
  );
}
