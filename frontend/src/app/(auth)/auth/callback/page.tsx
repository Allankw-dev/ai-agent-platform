import { Suspense } from "react";
import type { Metadata } from "next";

import { AuthCallback } from "@/features/auth/auth-callback";

export const metadata: Metadata = { title: "Signing in" };

export default function Page() {
  return (
    <Suspense>
      <AuthCallback />
    </Suspense>
  );
}
