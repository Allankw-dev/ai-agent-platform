import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AcceptInvite } from "@/features/orgs/accept-invite";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { authState, resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation, router } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  nav.params = { token: "TOKEN123" };
});

describe("AcceptInvite", () => {
  it("does not consume the invitation until the user clicks", () => {
    routeApi({});
    renderWithQuery(<AcceptInvite />);
    expect(screen.getByText("me@example.com")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("accepts the invitation with the token from the link", async () => {
    routeApi({
      "POST /invitations/accept": {
        organization: { id: "org-9", name: "Acme Inc", slug: "acme", created_at: "x" },
        role: "developer",
      },
    });
    renderWithQuery(<AcceptInvite />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Accept invitation" }));

    expect(await screen.findByText("Welcome to Acme Inc")).toBeInTheDocument();
    expect(screen.getByText("You joined as Developer.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Acme Inc" })).toHaveAttribute(
      "href",
      "/orgs/org-9",
    );
    expect(callsTo("POST", "/invitations/accept")[0][1]).toMatchObject({
      body: { token: "TOKEN123" },
    });
  });

  it("lets someone on the wrong account switch to the invited one", async () => {
    routeApi({
      "POST /invitations/accept": apiError(
        403,
        "invitation_email_mismatch",
        "This invitation was sent to a different email address.",
      ),
    });
    renderWithQuery(<AcceptInvite />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Accept invitation" }));
    await user.click(await screen.findByRole("button", { name: "Sign out and switch account" }));

    expect(authState.signOut).toHaveBeenCalled();
    await waitFor(() =>
      expect(router.replace).toHaveBeenCalledWith("/login?next=%2Finvite%2FTOKEN123"),
    );
  });

  it.each([
    ["invitation_expired", 410, "This invitation has expired."],
    ["invitation_not_pending", 410, "This invitation is no longer valid."],
    ["invitation_not_found", 404, "This invitation link is not valid."],
  ])("shows %s clearly", async (code, status, message) => {
    routeApi({ "POST /invitations/accept": apiError(status, code, message) });
    renderWithQuery(<AcceptInvite />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Accept invitation" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Sign out and switch account" }),
    ).not.toBeInTheDocument();
  });
});
