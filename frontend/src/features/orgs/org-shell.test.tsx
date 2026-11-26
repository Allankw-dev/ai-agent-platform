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

  it("has an Agents tab that stays highlighted on nested agent pages", async () => {
    nav.pathname = "/orgs/org-1/agents/agent-1/edit";
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(<OrgShell>x</OrgShell>);
    const agents = await screen.findByRole("link", { name: "Agents" });
    expect(agents).toHaveAttribute("href", "/orgs/org-1/agents");
    expect(agents).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Members" })).not.toHaveAttribute("aria-current");
  });

  it("has a Runs tab that stays highlighted on a single run's page", async () => {
    nav.pathname = "/orgs/org-1/runs/run-9";
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(<OrgShell>x</OrgShell>);
    const runs = await screen.findByRole("link", { name: "Runs" });
    expect(runs).toHaveAttribute("href", "/orgs/org-1/runs");
    expect(runs).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Agents" })).not.toHaveAttribute("aria-current");
  });

  it("does not highlight Agents on other pages", async () => {
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(<OrgShell>x</OrgShell>);
    expect(await screen.findByRole("link", { name: "Agents" })).not.toHaveAttribute("aria-current");
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

  it("has an Integrations tab for roles that may see integrations, highlighted on its page", async () => {
    nav.pathname = "/orgs/org-1/integrations";
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(<OrgShell>x</OrgShell>);
    const tab = await screen.findByRole("link", { name: "Integrations" });
    expect(tab).toHaveAttribute("href", "/orgs/org-1/integrations");
    expect(tab).toHaveAttribute("aria-current", "page");
  });

  it.each(["owner", "developer"])("shows the Integrations tab to a %s", async (role) => {
    routeApi({ "GET /organizations/org-1": { ...ORG, role } });
    renderWithQuery(<OrgShell>x</OrgShell>);
    expect(await screen.findByRole("link", { name: "Integrations" })).toBeInTheDocument();
  });

  it("has a Usage tab for roles that may see usage, highlighted on its page", async () => {
    nav.pathname = "/orgs/org-1/usage";
    routeApi({ "GET /organizations/org-1": ORG });
    renderWithQuery(<OrgShell>x</OrgShell>);
    const tab = await screen.findByRole("link", { name: "Usage" });
    expect(tab).toHaveAttribute("href", "/orgs/org-1/usage");
    expect(tab).toHaveAttribute("aria-current", "page");
  });

  it("hides the Usage tab from members", async () => {
    routeApi({ "GET /organizations/org-1": { ...ORG, role: "member" } });
    renderWithQuery(<OrgShell>x</OrgShell>);
    await screen.findByRole("link", { name: "Members" });
    expect(screen.queryByRole("link", { name: "Usage" })).not.toBeInTheDocument();
  });

  it("hides the Integrations tab from members", async () => {
    routeApi({ "GET /organizations/org-1": { ...ORG, role: "member" } });
    renderWithQuery(<OrgShell>x</OrgShell>);
    await screen.findByRole("link", { name: "Members" });
    expect(screen.queryByRole("link", { name: "Integrations" })).not.toBeInTheDocument();
  });

  describe("the Approvals tab", () => {
    const PENDING = "GET /organizations/org-1/approvals";
    const waiting = (total: number) => ({ items: [], total, limit: 1, offset: 0 });

    it.each(["owner", "admin", "developer"] as const)("is shown to a %s", async (role) => {
      routeApi({ "GET /organizations/org-1": { ...ORG, role }, [PENDING]: waiting(0) });
      renderWithQuery(<OrgShell>x</OrgShell>);
      const tab = await screen.findByRole("link", { name: "Approvals" });
      expect(tab).toHaveAttribute("href", "/orgs/org-1/approvals");
    });

    it("is hidden from members, who also never trigger the count request", async () => {
      routeApi({ "GET /organizations/org-1": { ...ORG, role: "member" } });
      renderWithQuery(<OrgShell>x</OrgShell>);
      await screen.findByRole("link", { name: "Members" });
      expect(screen.queryByRole("link", { name: /Approvals/ })).toBeNull();
      expect(apiFetch.mock.calls.some(([path]) => String(path).includes("/approvals"))).toBe(false);
    });

    it("shows how many are waiting, and says so to screen readers", async () => {
      routeApi({ "GET /organizations/org-1": ORG, [PENDING]: waiting(3) });
      renderWithQuery(<OrgShell>x</OrgShell>);
      const tab = await screen.findByRole("link", { name: "Approvals (3 waiting)" });
      expect(tab).toHaveTextContent("3");
      expect(apiFetch).toHaveBeenCalledWith(
        "/organizations/org-1/approvals",
        expect.objectContaining({ query: { status: "pending", limit: 1 } }),
      );
    });

    it("shows no number when nothing is waiting", async () => {
      routeApi({ "GET /organizations/org-1": ORG, [PENDING]: waiting(0) });
      renderWithQuery(<OrgShell>x</OrgShell>);
      const tab = await screen.findByRole("link", { name: "Approvals" });
      expect(tab).not.toHaveTextContent(/\d/);
    });

    it("still shows the tab, without a number, if the count cannot be loaded", async () => {
      routeApi({
        "GET /organizations/org-1": ORG,
        [PENDING]: apiError(500, "boom", "The server had a problem."),
      });
      renderWithQuery(<OrgShell>x</OrgShell>);
      expect(await screen.findByRole("link", { name: "Approvals" })).toBeInTheDocument();
    });

    it("is the active tab on the inbox and on an approval", async () => {
      routeApi({ "GET /organizations/org-1": ORG, [PENDING]: waiting(0) });
      nav.pathname = "/orgs/org-1/approvals/appr-1";
      renderWithQuery(<OrgShell>x</OrgShell>);
      const tab = await screen.findByRole("link", { name: "Approvals" });
      expect(tab).toHaveAttribute("aria-current", "page");
    });
  });
});
