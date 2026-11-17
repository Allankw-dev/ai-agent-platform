import { Suspense } from "react";
import type { Metadata } from "next";

import { Spinner } from "@/components/ui/spinner";
import { IntegrationsPage } from "@/features/integrations/integrations-page";

export const metadata: Metadata = { title: "Integrations" };

export default function Page() {
  return (
    <Suspense fallback={<Spinner label="Loading integrations" />}>
      <IntegrationsPage />
    </Suspense>
  );
}
