import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ForgotPasswordForm } from "@/features/auth/forgot-password-form";
import { auth, resetSupabase } from "@/test/supabase-mock";

vi.mock("@/lib/supabase", async (importOriginal) =>
  (await import("@/test/supabase-mock")).supabaseFactory(importOriginal),
);

beforeEach(resetSupabase);

async function submit(email: string) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText("Email"), email);
  await user.click(screen.getByRole("button", { name: "Send reset link" }));
}

describe("ForgotPasswordForm", () => {
  it("requires a valid email", async () => {
    render(<ForgotPasswordForm />);
    await submit("nope");
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(auth.resetPasswordForEmail).not.toHaveBeenCalled();
  });

  it("sends the link and points it at the callback, then the reset page", async () => {
    auth.resetPasswordForEmail.mockResolvedValue({ error: null });
    render(<ForgotPasswordForm />);
    await submit("ada@example.com");
    expect(await screen.findByText(/If an account exists/)).toBeInTheDocument();
    expect(auth.resetPasswordForEmail).toHaveBeenCalledWith("ada@example.com", {
      redirectTo: "http://localhost:3000/auth/callback?next=/reset-password",
    });
  });

  it("gives the same answer whether or not the account exists", async () => {
    auth.resetPasswordForEmail.mockResolvedValue({
      error: { message: "User not found", status: 400 },
    });
    render(<ForgotPasswordForm />);
    await submit("ghost@example.com");
    expect(await screen.findByText(/If an account exists/)).toBeInTheDocument();
    expect(screen.queryByText(/not found/i)).not.toBeInTheDocument();
  });

  it("does report being rate limited", async () => {
    auth.resetPasswordForEmail.mockResolvedValue({ error: { message: "rate limit", status: 429 } });
    render(<ForgotPasswordForm />);
    await submit("ada@example.com");
    expect(await screen.findByText(/Too many attempts/)).toBeInTheDocument();
    expect(screen.queryByText(/If an account exists/)).not.toBeInTheDocument();
  });
});
