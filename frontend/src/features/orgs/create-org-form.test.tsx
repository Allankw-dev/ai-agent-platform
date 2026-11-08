import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateOrgForm } from "@/features/orgs/create-org-form";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { authProviderMock } from "@/test/auth-mock";
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

void authProviderMock;

beforeEach(() => {
  resetNavigation();
  apiFetch.mockReset();
});

describe("CreateOrgForm", () => {
  it("validates the name and slug locally", async () => {
    routeApi({});
    renderWithQuery(<CreateOrgForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Organization name"), "A");
    await user.type(screen.getByLabelText("URL name (optional)"), "Bad Slug");
    await user.click(screen.getByRole("button", { name: "Create organization" }));
    expect(await screen.findByText("Use at least 2 characters.")).toBeInTheDocument();
    expect(
      screen.getByText(/lowercase letters, numbers and hyphens, starting/),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("creates the organization and opens it", async () => {
    routeApi({ "POST /organizations": { id: "org-1", name: "Acme", slug: "acme", role: "owner" } });
    renderWithQuery(<CreateOrgForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Organization name"), "  Acme  ");
    await user.click(screen.getByRole("button", { name: "Create organization" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/orgs/org-1"));
    expect(callsTo("POST", "/organizations")[0][1]).toMatchObject({
      body: { name: "Acme", slug: undefined },
    });
  });

  it("sends a chosen URL name, lower-cased", async () => {
    routeApi({ "POST /organizations": { id: "org-1" } });
    renderWithQuery(<CreateOrgForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Organization name"), "Acme");
    await user.type(screen.getByLabelText("URL name (optional)"), "ACME-Co");
    await user.click(screen.getByRole("button", { name: "Create organization" }));
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(callsTo("POST", "/organizations")[0][1]).toMatchObject({
      body: { name: "Acme", slug: "acme-co" },
    });
  });

  it("shows a taken URL name next to the field", async () => {
    routeApi({
      "POST /organizations": apiError(409, "slug_taken", "That URL name is already in use."),
    });
    renderWithQuery(<CreateOrgForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Organization name"), "Acme");
    await user.type(screen.getByLabelText("URL name (optional)"), "acme");
    await user.click(screen.getByRole("button", { name: "Create organization" }));
    expect(await screen.findByText("That URL name is already in use.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows other API errors", async () => {
    routeApi({ "POST /organizations": apiError(500, "boom", "The server had a problem.") });
    renderWithQuery(<CreateOrgForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Organization name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Create organization" }));
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});
