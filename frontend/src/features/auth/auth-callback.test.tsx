import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthCallback } from "@/features/auth/auth-callback";
import { nav, resetNavigation, router } from "@/test/next-navigation";
import { auth, resetSupabase } from "@/test/supabase-mock";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock("@/lib/supabase", async (importOriginal) =>
  (await import("@/test/supabase-mock")).supabaseFactory(importOriginal),
);

beforeEach(() => {
  resetNavigation();
  resetSupabase();
  window.location.hash = "";
});

describe("AuthCallback", () => {
  it("exchanges the code and continues to next", async () => {
    nav.search = new URLSearchParams({ code: "abc", next: "/reset-password" });
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });
    render(<AuthCallback />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/reset-password"));
    expect(auth.exchangeCodeForSession).toHaveBeenCalledWith("abc");
  });

  it("defaults to the dashboard and refuses unsafe destinations", async () => {
    nav.search = new URLSearchParams({ code: "abc", next: "//evil.example.com" });
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });
    render(<AuthCallback />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("exchanges the one-time code only once, even when effects run twice", async () => {
    nav.search = new URLSearchParams({ code: "abc" });
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });
    render(
      <StrictMode>
        <AuthCallback />
      </StrictMode>,
    );
    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    expect(auth.exchangeCodeForSession).toHaveBeenCalledTimes(1);
  });

  it("explains an expired or already used link", async () => {
    nav.search = new URLSearchParams({ code: "stale" });
    auth.exchangeCodeForSession.mockResolvedValue({ error: { message: "invalid grant" } });
    render(<AuthCallback />);
    expect(await screen.findByText(/not valid or has expired/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/login");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("shows the problem Supabase reports in the query string", async () => {
    nav.search = new URLSearchParams({ error_description: "Email link is invalid or has expired" });
    render(<AuthCallback />);
    expect(await screen.findByText("Email link is invalid or has expired")).toBeInTheDocument();
    expect(auth.exchangeCodeForSession).not.toHaveBeenCalled();
  });

  it("shows the problem Supabase reports in the URL fragment", async () => {
    window.location.hash = "#error=access_denied&error_description=Link+has+expired";
    render(<AuthCallback />);
    expect(await screen.findByText("Link has expired")).toBeInTheDocument();
  });

  it("continues when there is no code but a session already exists", async () => {
    auth.getSession.mockResolvedValue({ data: { session: { access_token: "t" } } });
    render(<AuthCallback />);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("fails clearly when there is neither a code nor a session", async () => {
    render(<AuthCallback />);
    expect(await screen.findByText(/not valid or has expired/)).toBeInTheDocument();
  });
});
