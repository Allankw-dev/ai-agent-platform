import { Suspense } from "react";
import type { Metadata } from "next";

import { AcceptInvite } from "@/features/orgs/accept-invite";

export const metadata: Metadata = { title: "Accept invitation" };

export default function Page() {
  return (
    <Suspense>
      <AcceptInvite />
    </Suspense>
  );
}
