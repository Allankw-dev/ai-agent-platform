import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InvitationsPanel } from "@/features/orgs/invitations-panel";
import type { Invitation, InvitationStatus } from "@/lib/api/types";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { renderWithQuery } from "@/test/render";

vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const LIST = "GET /organizations/org-1/invitations";
const CREATE = "POST /organizations/org-1/invitations";

const invitation = (id: string, email: string, status: InvitationStatus): Invitation => ({
  id,
  email,
  role: "member",
  status,
  expires_at: "2026-11-14T00:00:00Z",
  created_at: "2026-11-07T00:00:00Z",
});

const page = (items: Invitation[]) => ({ items, total: items.length, limit: 50, offset: 0 });

beforeEach(() => {
  resetAuth();
  apiFetch.mockReset();
});

describe("InvitationsPanel", () => {
  it("offers an owner admin, developer and member, but never owner", async () => {
    routeApi({ [LIST]: page([]) });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    const options = within(await screen.findByLabelText("Role")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Admin", "Developer", "Member"]);
  });

  it("offers an admin only roles below admin", async () => {
    routeApi({ [LIST]: page([]) });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="admin" />);
    const options = within(await screen.findByLabelText("Role")).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Developer", "Member"]);
  });

  it("validates the email before calling the API", async () => {
    routeApi({ [LIST]: page([]) });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "nope");
    await user.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(callsTo("POST", "/organizations/org-1/invitations")).toHaveLength(0);
  });

  it("creates an invitation and shows the one-time link, which can be copied", async () => {
    routeApi({
      [LIST]: page([]),
      [CREATE]: {
        ...invitation("i-1", "new@example.com", "pending"),
        role: "developer",
        invite_url: "http://localhost:3000/invite/TOKEN123",
      },
    });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "New@Example.com");
    await user.selectOptions(screen.getByLabelText("Role"), "developer");
    await user.click(screen.getByRole("button", { name: "Create invitation" }));

    const link = await screen.findByLabelText("Invitation link");
    expect(link).toHaveValue("http://localhost:3000/invite/TOKEN123");
    expect(callsTo("POST", "/organizations/org-1/invitations")[0][1]).toMatchObject({
      body: { email: "New@Example.com", role: "developer" },
    });

    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe("http://localhost:3000/invite/TOKEN123");
  });

  it("clears the email field after a successful invitation", async () => {
    routeApi({
      [LIST]: page([]),
      [CREATE]: { ...invitation("i-1", "a@x.com", "pending"), invite_url: "http://x/invite/T" },
    });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@x.com");
    await user.click(screen.getByRole("button", { name: "Create invitation" }));
    await screen.findByLabelText("Invitation link");
    expect(screen.getByLabelText("Email")).toHaveValue("");
  });

  it("explains why an invitation was refused", async () => {
    routeApi({
      [LIST]: page([]),
      [CREATE]: apiError(409, "already_member", "That person is already a member."),
    });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@x.com");
    await user.click(screen.getByRole("button", { name: "Create invitation" }));
    expect(await screen.findByText("That person is already a member.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Invitation link")).not.toBeInTheDocument();
  });

  it("lists invitations with their status, and only pending ones can be revoked", async () => {
    routeApi({
      [LIST]: page([
        invitation("i-1", "pending@x.com", "pending"),
        invitation("i-2", "done@x.com", "accepted"),
        invitation("i-3", "late@x.com", "expired"),
        invitation("i-4", "gone@x.com", "revoked"),
      ]),
    });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    await screen.findByText("pending@x.com");

    expect(screen.getAllByRole("button", { name: /Revoke invitation/ })).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Revoke invitation for pending@x.com" }),
    ).toBeInTheDocument();
    for (const status of ["pending", "accepted", "expired", "revoked"]) {
      expect(screen.getByText(status)).toBeInTheDocument();
    }
  });

  it("revokes a pending invitation", async () => {
    routeApi({
      [LIST]: page([invitation("i-1", "pending@x.com", "pending")]),
      "DELETE /organizations/org-1/invitations/i-1": undefined,
    });
    renderWithQuery(<InvitationsPanel orgId="org-1" myRole="owner" />);
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Revoke invitation for pending@x.com" }));
    await waitFor(() =>
      expect(callsTo("DELETE", "/organizations/org-1/invitations/i-1")).toHaveLength(1),
    );
  });
});
