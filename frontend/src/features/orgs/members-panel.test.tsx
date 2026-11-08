import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MembersPanel } from "@/features/orgs/members-panel";
import type { Member, OrgRole } from "@/lib/api/types";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { ME, authState, resetAuth } from "@/test/auth-mock";
import { resetNavigation, router } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const member = (user_id: string, email: string, role: OrgRole): Member => ({
  user_id,
  email,
  full_name: null,
  role,
  joined_at: "2026-11-01T00:00:00Z",
});

const MEMBERS_PATH = "GET /organizations/org-1/members";
const people = (myRole: OrgRole): Member[] => [
  member(ME.id, ME.email, myRole),
  member("u-owner", "owner@x.com", "owner"),
  member("u-admin", "admin@x.com", "admin"),
  member("u-dev", "dev@x.com", "developer"),
  member("u-member", "member@x.com", "member"),
];

function page(items: Member[], total = items.length) {
  return { items, total, limit: 50, offset: 0 };
}

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
});

const rowFor = (email: string) => screen.getByText(email).closest("li") as HTMLElement;

describe("MembersPanel", () => {
  it("lets an owner change anyone else's role, but not their own", async () => {
    routeApi({ [MEMBERS_PATH]: page(people("owner")) });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    await screen.findByText("admin@x.com");

    for (const email of ["owner@x.com", "admin@x.com", "dev@x.com", "member@x.com"]) {
      expect(screen.getByRole("combobox", { name: `Role for ${email}` })).toBeEnabled();
    }
    expect(
      screen.queryByRole("combobox", { name: `Role for ${ME.email}` }),
    ).not.toBeInTheDocument();
    expect(within(rowFor(ME.email)).getByText("You")).toBeInTheDocument();
  });

  it("offers an admin only the roles below theirs, on people below them", async () => {
    routeApi({ [MEMBERS_PATH]: page(people("admin")) });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="admin" />);
    await screen.findByText("dev@x.com");

    expect(
      screen.queryByRole("combobox", { name: "Role for owner@x.com" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Role for admin@x.com" }),
    ).not.toBeInTheDocument();
    const select = screen.getByRole("combobox", { name: "Role for dev@x.com" });
    const options = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Developer", "Member"]);
  });

  it("gives a plain member no controls except leaving", async () => {
    routeApi({ [MEMBERS_PATH]: page(people("member")) });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="member" />);
    await screen.findByText("owner@x.com");

    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(screen.getAllByRole("button", { name: /Remove|Leave/ })).toHaveLength(1);
    expect(screen.getByRole("button", { name: `Leave ${ME.email}` })).toBeInTheDocument();
  });

  it("changes a role through the API", async () => {
    routeApi({
      [MEMBERS_PATH]: page(people("owner")),
      "PATCH /organizations/org-1/members/u-member": { role: "developer" },
    });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    const select = await screen.findByRole("combobox", { name: "Role for member@x.com" });
    await userEvent.setup().selectOptions(select, "developer");
    await waitFor(() =>
      expect(callsTo("PATCH", "/organizations/org-1/members/u-member")).toHaveLength(1),
    );
    expect(callsTo("PATCH", "/organizations/org-1/members/u-member")[0][1]).toMatchObject({
      body: { role: "developer" },
    });
  });

  it("asks for confirmation before removing someone", async () => {
    routeApi({
      [MEMBERS_PATH]: page(people("owner")),
      "DELETE /organizations/org-1/members/u-dev": undefined,
    });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove dev@x.com" }));

    expect(callsTo("DELETE", "/organizations/org-1/members/u-dev")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Confirm remove" }));
    await waitFor(() =>
      expect(callsTo("DELETE", "/organizations/org-1/members/u-dev")).toHaveLength(1),
    );
  });

  it("lets you back out of a removal", async () => {
    routeApi({ [MEMBERS_PATH]: page(people("owner")) });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove dev@x.com" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Confirm remove" })).not.toBeInTheDocument();
    expect(callsTo("DELETE", "/organizations/org-1/members/u-dev")).toHaveLength(0);
  });

  it("returns to the dashboard after you leave", async () => {
    routeApi({
      [MEMBERS_PATH]: page(people("member")),
      [`DELETE /organizations/org-1/members/${ME.id}`]: undefined,
    });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="member" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: `Leave ${ME.email}` }));
    await user.click(screen.getByRole("button", { name: "Confirm leave" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the API's reason when a change is refused", async () => {
    routeApi({
      [MEMBERS_PATH]: page(people("owner")),
      "DELETE /organizations/org-1/members/u-owner": apiError(
        409,
        "last_owner",
        "An organization must keep at least one owner.",
      ),
    });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove owner@x.com" }));
    await user.click(screen.getByRole("button", { name: "Confirm remove" }));
    expect(
      await screen.findByText("An organization must keep at least one owner."),
    ).toBeInTheDocument();
  });

  it("shows names when people have them and counts members", async () => {
    routeApi({
      [MEMBERS_PATH]: page([{ ...member("u-1", "ada@x.com", "owner"), full_name: "Ada Lovelace" }]),
    });
    authState.user = { id: "u-1", email: "ada@x.com" };
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@x.com")).toBeInTheDocument();
    expect(screen.getByText("1 person in this organization.")).toBeInTheDocument();
  });

  it("loads more when there are more members than shown", async () => {
    routeApi({ [MEMBERS_PATH]: page(people("owner"), 120) });
    renderWithQuery(<MembersPanel orgId="org-1" myRole="owner" />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Show more" }));
    await waitFor(() => {
      const limits = callsTo("GET", "/organizations/org-1/members").map(
        ([, options]) => (options as { query: { limit: number } }).query.limit,
      );
      expect(limits).toContain(100);
    });
  });
});
