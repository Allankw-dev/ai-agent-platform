import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { AgentCreatePage } from "@/features/agents/agent-create-page";

export const metadata: Metadata = { title: "Create agent" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading" />}>
      <AgentCreatePage />
    </Suspense>
  );
}
