import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "@/features/auth/login-form";
import { authState, resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation, router } from "@/test/next-navigation";
import { auth, resetSupabase } from "@/test/supabase-mock";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/supabase", async (importOriginal) =>
  (await import("@/test/supabase-mock")).supabaseFactory(importOriginal),
);

beforeEach(() => {
  resetNavigation();
  resetAuth();
  resetSupabase();
  authState.status = "unauthenticated";
  authState.user = null;
});

async function fillAndSubmit(email: string, password: string) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText("Email"), email);
  if (password) await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  it("validates before calling Supabase", async () => {
    render(<LoginForm />);
    await fillAndSubmit("", "");
    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
  });

  it("rejects a malformed email", async () => {
    render(<LoginForm />);
    await fillAndSubmit("not-an-email", "secret");
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
  });

  it("signs in and goes to the dashboard", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null });
    render(<LoginForm />);
    await fillAndSubmit(" ada@example.com ", "correct horse");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
    expect(auth.signInWithPassword).toHaveBeenCalledWith({
      email: "ada@example.com",
      password: "correct horse",
    });
  });

  it("returns to the page the user came from", async () => {
    nav.search = new URLSearchParams({ next: "/invite/abc" });
    auth.signInWithPassword.mockResolvedValue({ error: null });
    render(<LoginForm />);
    await fillAndSubmit("ada@example.com", "pw");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/invite/abc"));
  });

  it("ignores an unsafe next parameter", async () => {
    nav.search = new URLSearchParams({ next: "https://evil.example.com" });
    auth.signInWithPassword.mockResolvedValue({ error: null });
    render(<LoginForm />);
    await fillAndSubmit("ada@example.com", "pw");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows a friendly message for wrong credentials and stays on the page", async () => {
    auth.signInWithPassword.mockResolvedValue({
      error: { message: "Invalid login credentials", status: 400 },
    });
    render(<LoginForm />);
    await fillAndSubmit("ada@example.com", "wrong");
    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("explains an unconfirmed email", async () => {
    auth.signInWithPassword.mockResolvedValue({
      error: { message: "Email not confirmed", status: 400 },
    });
    render(<LoginForm />);
    await fillAndSubmit("ada@example.com", "pw");
    expect(await screen.findByText(/Confirm your email first/)).toBeInTheDocument();
  });

  it("survives the network failing", async () => {
    auth.signInWithPassword.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<LoginForm />);
    await fillAndSubmit("ada@example.com", "pw");
    expect(
      await screen.findByText(/Could not reach the authentication service/),
    ).toBeInTheDocument();
  });

  it("sends signed-in visitors straight to the app", () => {
    authState.status = "authenticated";
    render(<LoginForm />);
    expect(router.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("links to registration and password recovery, keeping next", () => {
    nav.search = new URLSearchParams({ next: "/invite/abc" });
    render(<LoginForm />);
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute(
      "href",
      "/register?next=%2Finvite%2Fabc",
    );
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});
