import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RegisterForm } from "@/features/auth/register-form";
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

async function submit(email: string, password: string, confirmation = password) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText("Email"), email);
  if (password) await user.type(screen.getByLabelText("Password"), password);
  if (confirmation) await user.type(screen.getByLabelText("Repeat password"), confirmation);
  await user.click(screen.getByRole("button", { name: "Create account" }));
}

describe("RegisterForm", () => {
  it("validates every field", async () => {
    render(<RegisterForm />);
    await submit("", "");
    expect(await screen.findByText("Enter your email address.")).toBeInTheDocument();
    expect(screen.getByText("Choose a password.")).toBeInTheDocument();
    expect(screen.getByText("Repeat the password.")).toBeInTheDocument();
    expect(auth.signUp).not.toHaveBeenCalled();
  });

  it("requires a long enough password", async () => {
    render(<RegisterForm />);
    await submit("ada@example.com", "short");
    expect(
      await screen.findByText(/at least 8 characters/, { selector: "[role=alert]" }),
    ).toBeInTheDocument();
    expect(auth.signUp).not.toHaveBeenCalled();
  });

  it("requires the repeated password to match", async () => {
    render(<RegisterForm />);
    await submit("ada@example.com", "long-enough-1", "long-enough-2");
    expect(await screen.findByText("The passwords do not match.")).toBeInTheDocument();
    expect(auth.signUp).not.toHaveBeenCalled();
  });

  it("asks the user to check their email when confirmation is required", async () => {
    auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
    render(<RegisterForm />);
    await submit("ada@example.com", "long-enough-1");
    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(screen.getByText(/ada@example.com/)).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();

    const [credentials] = auth.signUp.mock.calls[0];
    expect(credentials.email).toBe("ada@example.com");
    expect(credentials.options.emailRedirectTo).toBe(
      "http://localhost:3000/auth/callback?next=%2Fdashboard",
    );
  });

  it("carries next through the confirmation link", async () => {
    nav.search = new URLSearchParams({ next: "/invite/abc" });
    auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
    render(<RegisterForm />);
    await submit("ada@example.com", "long-enough-1");
    await screen.findByRole("heading", { name: "Check your email" });
    expect(auth.signUp.mock.calls[0][0].options.emailRedirectTo).toContain("next=%2Finvite%2Fabc");
  });

  it("goes straight in when the project does not require confirmation", async () => {
    auth.signUp.mockResolvedValue({ data: { session: { access_token: "t" } }, error: null });
    render(<RegisterForm />);
    await submit("ada@example.com", "long-enough-1");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows Supabase errors in plain language", async () => {
    auth.signUp.mockResolvedValue({
      data: { session: null },
      error: { message: "Password is known to be weak", status: 422 },
    });
    render(<RegisterForm />);
    await submit("ada@example.com", "password123");
    expect(await screen.findByText(/too easy to guess/)).toBeInTheDocument();
  });

  it("lets people resend the email, but not immediately", async () => {
    auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
    render(<RegisterForm />);
    await submit("ada@example.com", "long-enough-1");
    const resend = await screen.findByRole("button", { name: /Resend email in/ });
    expect(resend).toBeDisabled();
    expect(auth.resend).not.toHaveBeenCalled();
  });
});
