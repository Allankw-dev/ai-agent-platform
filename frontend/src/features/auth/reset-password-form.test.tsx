import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResetPasswordForm } from "@/features/auth/reset-password-form";
import { authState, resetAuth } from "@/test/auth-mock";
import { resetNavigation } from "@/test/next-navigation";
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
});

async function submit(password: string, confirmation: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("New password"), password);
  await user.type(screen.getByLabelText("Repeat new password"), confirmation);
  await user.click(screen.getByRole("button", { name: "Update password" }));
}

describe("ResetPasswordForm", () => {
  it("rejects people who did not arrive through a valid reset link", () => {
    authState.status = "unauthenticated";
    render(<ResetPasswordForm />);
    expect(screen.getByText("This link is not valid")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });

  it("waits while the session is being restored", () => {
    authState.status = "loading";
    render(<ResetPasswordForm />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("This link is not valid")).not.toBeInTheDocument();
  });

  it("checks the new password before sending it", async () => {
    render(<ResetPasswordForm />);
    await submit("long-enough-1", "different-1");
    expect(await screen.findByText("The passwords do not match.")).toBeInTheDocument();
    expect(auth.updateUser).not.toHaveBeenCalled();
  });

  it("updates the password", async () => {
    auth.updateUser.mockResolvedValue({ error: null });
    render(<ResetPasswordForm />);
    await submit("long-enough-1", "long-enough-1");
    expect(await screen.findByText("Password updated")).toBeInTheDocument();
    expect(auth.updateUser).toHaveBeenCalledWith({ password: "long-enough-1" });
  });

  it("shows why Supabase refused", async () => {
    auth.updateUser.mockResolvedValue({
      error: { message: "New password should be different from the old password.", status: 422 },
    });
    render(<ResetPasswordForm />);
    await submit("long-enough-1", "long-enough-1");
    expect(await screen.findByText(/not used before/)).toBeInTheDocument();
  });
});
