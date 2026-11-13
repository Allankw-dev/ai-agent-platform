import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { AgentsListPage } from "@/features/agents/agents-list-page";

export const metadata: Metadata = { title: "Agents" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading agents" />}>
      <AgentsListPage />
    </Suspense>
  );
}
