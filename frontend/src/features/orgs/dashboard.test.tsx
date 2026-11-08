import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Dashboard } from "@/features/orgs/dashboard";
import { apiError, apiFetch, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { renderWithQuery } from "@/test/render";

vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

beforeEach(() => {
  resetAuth();
  apiFetch.mockReset();
});

describe("Dashboard", () => {
  it("invites people with no organizations to create one", async () => {
    routeApi({ "GET /organizations": { items: [], total: 0, limit: 100, offset: 0 } });
    renderWithQuery(<Dashboard />);
    expect(await screen.findByText("Create your first organization")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create organization" })).toHaveAttribute(
      "href",
      "/orgs/new",
    );
  });

  it("lists organizations with the caller's role, each linking to its page", async () => {
    routeApi({
      "GET /organizations": {
        items: [
          { id: "o1", name: "Acme Inc", slug: "acme", created_at: "x", role: "owner" },
          { id: "o2", name: "Beta Co", slug: "beta", created_at: "x", role: "member" },
        ],
        total: 2,
        limit: 100,
        offset: 0,
      },
    });
    renderWithQuery(<Dashboard />);
    expect(await screen.findByRole("link", { name: /Acme Inc/ })).toHaveAttribute(
      "href",
      "/orgs/o1",
    );
    expect(screen.getByRole("link", { name: /Beta Co/ })).toHaveAttribute("href", "/orgs/o2");
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Member")).toBeInTheDocument();
  });

  it("shows loading failures", async () => {
    routeApi({ "GET /organizations": apiError(500, "boom", "The server had a problem.") });
    renderWithQuery(<Dashboard />);
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});
