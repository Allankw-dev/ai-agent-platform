import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgShell } from "@/features/orgs/org-shell";
import { apiError, apiFetch, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const ORG = { id: "org-1", name: "Acme Inc", slug: "acme", created_at: "x", role: "admin" };

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  nav.params = { orgId: "org-1" };
  nav.pathname = "/orgs/org-1";
});

describe("OrgShell", () => {
  it("shows the organization, the caller's role and the active tab", async () => {
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(
      <OrgShell>
        <p>page content</p>
      </OrgShell>,
    );
    expect(await screen.findByRole("heading", { name: "Acme Inc" })).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Members" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Members" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members",
    );
  });

  it("marks the members tab on the members page", async () => {
    nav.pathname = "/orgs/org-1/members";
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(<OrgShell>x</OrgShell>);
    expect(await screen.findByRole("link", { name: "Members" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows a not-found page, and no content, when the API says 404", async () => {
    routeApi({
      "GET /organizations/org-1": apiError(
        404,
        "organization_not_found",
        "Organization not found.",
      ),
    });
    renderWithQuery(
      <OrgShell>
        <p>page content</p>
      </OrgShell>,
    );
    expect(await screen.findByText("Organization not found")).toBeInTheDocument();
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to your organizations" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });

  it("shows other failures as errors", async () => {
    routeApi({ "GET /organizations/org-1": apiError(500, "boom", "The server had a problem.") });
    renderWithQuery(<OrgShell>x</OrgShell>);
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});
