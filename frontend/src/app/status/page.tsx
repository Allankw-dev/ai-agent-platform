import type { Metadata } from "next";

import { StatusPanel } from "@/features/status/status-panel";

export const metadata: Metadata = { title: "System status" };

export default function StatusPage() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">System status</h1>
      <p className="mt-3 mb-10 text-muted-foreground">
        Live health of the services behind the platform, read from the backend API.
      </p>
      <StatusPanel />
    </div>
  );
}
