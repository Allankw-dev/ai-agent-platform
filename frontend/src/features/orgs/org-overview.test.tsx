import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgProvider } from "@/features/orgs/org-context";
import { OrgOverview } from "@/features/orgs/org-overview";
import type { OrgRole, Organization } from "@/lib/api/types";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
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

const org = (role: OrgRole): Organization => ({
  id: "org-1",
  name: "Acme Inc",
  slug: "acme-inc",
  created_at: "2026-11-01T00:00:00Z",
  role,
});

const renderOverview = (role: OrgRole) =>
  renderWithQuery(
    <OrgProvider value={org(role)}>
      <OrgOverview />
    </OrgProvider>,
  );

beforeEach(() => {
  resetNavigation();
  apiFetch.mockReset();
  routeApi({});
});

describe("OrgOverview", () => {
  it("shows plain members the details and nothing editable", () => {
    renderOverview("member");
    expect(screen.getByText("acme-inc")).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete this organization" }),
    ).not.toBeInTheDocument();
  });

  it("lets admins rename but not delete", () => {
    renderOverview("admin");
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete this organization" }),
    ).not.toBeInTheDocument();
  });

  it("renames the organization", async () => {
    routeApi({ "PATCH /organizations/org-1": { ...org("admin"), name: "Acme Corp" } });
    renderOverview("admin");
    const user = userEvent.setup();
    const input = screen.getByLabelText("Name");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.clear(input);
    await user.type(input, "Acme Corp");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Name updated.")).toBeInTheDocument();
    expect(callsTo("PATCH", "/organizations/org-1")[0][1]).toMatchObject({
      body: { name: "Acme Corp" },
    });
  });

  it("validates the new name", async () => {
    renderOverview("admin");
    const user = userEvent.setup();
    const input = screen.getByLabelText("Name");
    await user.clear(input);
    await user.type(input, "A");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Use at least 2 characters.")).toBeInTheDocument();
    expect(callsTo("PATCH", "/organizations/org-1")).toHaveLength(0);
  });

  it("makes the owner type the name before deleting", async () => {
    routeApi({ "DELETE /organizations/org-1": undefined });
    renderOverview("owner");
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Delete this organization" });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText('Type "Acme Inc" to confirm'), "acme inc");
    expect(button).toBeDisabled(); // case matters

    await user.clear(screen.getByLabelText('Type "Acme Inc" to confirm'));
    await user.type(screen.getByLabelText('Type "Acme Inc" to confirm'), "Acme Inc");
    expect(button).toBeEnabled();
    await user.click(button);
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/dashboard"));
    expect(callsTo("DELETE", "/organizations/org-1")).toHaveLength(1);
  });

  it("stays put and explains when deleting fails", async () => {
    routeApi({
      "DELETE /organizations/org-1": apiError(
        403,
        "forbidden",
        "Your role does not allow this action.",
      ),
    });
    renderOverview("owner");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Type "Acme Inc" to confirm'), "Acme Inc");
    await user.click(screen.getByRole("button", { name: "Delete this organization" }));
    expect(await screen.findByText("Your role does not allow this action.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });
});
