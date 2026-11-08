import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProfilePage } from "@/features/profile/profile-page";
import { apiFetch, routeApi } from "@/test/api-mock";
import { authState, resetAuth } from "@/test/auth-mock";
import { resetNavigation, router } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";
import { auth, resetSupabase } from "@/test/supabase-mock";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);
vi.mock("@/lib/supabase", async (importOriginal) =>
  (await import("@/test/supabase-mock")).supabaseFactory(importOriginal),
);

beforeEach(() => {
  resetNavigation();
  resetAuth();
  resetSupabase();
  apiFetch.mockReset();
  routeApi({
    "GET /auth/me": {
      id: "user-me",
      email: "me@example.com",
      full_name: null,
      avatar_url: null,
      is_super_admin: false,
      created_at: "2026-11-07T10:00:00Z",
    },
  });
});

describe("ProfilePage", () => {
  it("shows the account details", async () => {
    renderWithQuery(<ProfilePage />);
    expect(await screen.findByText("me@example.com")).toBeInTheDocument();
    expect(screen.getByText("user-me")).toBeInTheDocument();
  });

  it("signs out and returns to the home page", async () => {
    renderWithQuery(<ProfilePage />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Sign out" }));
    expect(authState.signOut).toHaveBeenCalled();
    expect(router.replace).toHaveBeenCalledWith("/");
  });

  it("checks the new password before sending it", async () => {
    renderWithQuery(<ProfilePage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "long-enough-1");
    await user.type(screen.getByLabelText("Repeat new password"), "different-1");
    await user.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText("The passwords do not match.")).toBeInTheDocument();
    expect(auth.updateUser).not.toHaveBeenCalled();
  });

  it("changes the password and clears the fields", async () => {
    auth.updateUser.mockResolvedValue({ error: null });
    renderWithQuery(<ProfilePage />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "long-enough-1");
    await user.type(screen.getByLabelText("Repeat new password"), "long-enough-1");
    await user.click(screen.getByRole("button", { name: "Update password" }));
    expect(await screen.findByText("Password updated.")).toBeInTheDocument();
    expect(auth.updateUser).toHaveBeenCalledWith({ password: "long-enough-1" });
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });
});
