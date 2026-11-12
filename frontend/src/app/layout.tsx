import type { Metadata } from "next";

import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Agent Platform", template: "%s | Agent Platform" },
  description:
    "Build AI agents, connect your tools, and approve what matters. Every action is validated, permissioned and logged.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      {/* Browser extensions (Grammarly, password managers) add attributes to <body> before React
          loads. suppressHydrationWarning ignores that one element's attributes only. */}
      <body className="flex min-h-full flex-col" suppressHydrationWarning>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
