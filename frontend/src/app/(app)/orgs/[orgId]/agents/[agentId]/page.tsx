import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { AgentDetailPage } from "@/features/agents/agent-detail-page";

export const metadata: Metadata = { title: "Agent" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading agent" />}>
      <AgentDetailPage />
    </Suspense>
  );
}
