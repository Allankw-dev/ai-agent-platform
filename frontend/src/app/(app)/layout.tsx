import { Suspense } from "react";

import { Spinner } from "@/components/ui/spinner";
import { RequireAuth } from "@/features/auth/require-auth";
import { AppHeader } from "@/features/orgs/app-header";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    // RequireAuth reads the current path, which is only known at request time.
    <Suspense
      fallback={
        <div className="grid min-h-64 place-items-center p-8">
          <Spinner />
        </div>
      }
    >
      <RequireAuth>
        <AppHeader />
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">{children}</main>
      </RequireAuth>
    </Suspense>
  );
}
