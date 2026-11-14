import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentDetailPage } from "@/features/agents/agent-detail-page";
import type { AgentRead, OrgRole } from "@/lib/api/types";
import { agent, inOrg, pageOf, summary, version } from "@/test/agents";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
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

const AGENT = "/organizations/org-1/agents/agent-1";

const v1 = version(1, { change_note: "First draft", created_at: "2026-11-09T09:00:00Z" });
const v2 = version(2, {
  change_note: "Added the calculator",
  objectives: "Always show your working.",
  limits: {
    max_iterations: 6,
    timeout_seconds: 90,
    max_total_tokens: 20_000,
    cost_budget_usd: 0.5,
  },
  tools: [
    {
      tool_key: "utility.calculate",
      name: "Calculator",
      description: "d",
      is_sensitive: false,
      requires_approval: true,
      config: {},
    },
  ],
});

function routes(overrides: Record<string, unknown> = {}, current: AgentRead = agent()) {
  routeApi({
    [`GET ${AGENT}`]: current,
    [`GET ${AGENT}/versions`]: pageOf([summary(v2), summary(v1)]),
    [`GET ${AGENT}/versions/1`]: v1,
    ...overrides,
  });
}
const renderPage = (role: OrgRole) => renderWithQuery(inOrg(role, <AgentDetailPage />));

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  nav.params = { orgId: "org-1", agentId: "agent-1" };
});

describe("AgentDetailPage", () => {
  it("shows the agent and its current configuration", async () => {
    routes({}, agent({ current_version: v2 }));
    renderPage("owner");
    expect(await screen.findByRole("heading", { name: "Math helper" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Answers arithmetic questions.")).toBeInTheDocument();
    const config = screen.getByText("Current configuration").closest("div")!.parentElement!;
    expect(within(config).getByText("You help with maths.")).toBeInTheDocument();
    expect(within(config).getByText("Always show your working.")).toBeInTheDocument();
    expect(within(config).getByText("Calculator")).toBeInTheDocument();
    expect(within(config).getByText("Needs approval")).toBeInTheDocument();
    expect(
      within(config).getByText(/6 model calls, 90 s, 20,000 tokens, cost budget \$0.5/),
    ).toBeInTheDocument();
  });

  it("says when an agent has no tools", async () => {
    routes();
    renderPage("owner");
    expect(
      await screen.findByText(/No tools: the agent can only answer in text/),
    ).toBeInTheDocument();
  });

  it("gives managers every action", async () => {
    routes();
    renderPage("developer");
    expect(await screen.findByRole("link", { name: "Edit" })).toHaveAttribute(
      "href",
      "/orgs/org-1/agents/agent-1/edit",
    );
    for (const name of ["Disable", "Duplicate", "Delete"]) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
  });

  it("lets a manager run the agent from its page, and links to its runs", async () => {
    routes();
    renderPage("developer");
    expect(await screen.findByRole("button", { name: "Run agent" })).toBeEnabled();
    expect(screen.getByRole("link", { name: "See this agent's runs" })).toHaveAttribute(
      "href",
      "/orgs/org-1/runs?agent=agent-1",
    );
  });

  it("does not offer to run a disabled agent", async () => {
    routes({}, agent({ status: "disabled" }));
    renderPage("owner");
    expect(
      await screen.findByText("This agent is disabled. Enable it to run it."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run agent" })).not.toBeInTheDocument();
  });

  it("gives members a read-only page", async () => {
    routes();
    renderPage("member");
    await screen.findByRole("heading", { name: "Math helper" });
    expect(screen.queryByRole("button", { name: "Run agent" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Edit" })).not.toBeInTheDocument();
    for (const name of ["Disable", "Activate", "Enable", "Duplicate", "Delete"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    await screen.findByText("Version history");
    expect(screen.queryByRole("button", { name: /Restore version/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View version 1" })).toBeInTheDocument();
  });

  it.each([
    ["draft", "Activate", "active"],
    ["active", "Disable", "disabled"],
    ["disabled", "Enable", "active"],
  ] as const)("a %s agent offers “%s”, which sets it to %s", async (status, label, next) => {
    routes({ [`PATCH ${AGENT}`]: agent({ status: next }) }, agent({ status }));
    renderPage("owner");
    await userEvent.setup().click(await screen.findByRole("button", { name: label }));
    await waitFor(() => expect(callsTo("PATCH", AGENT)).toHaveLength(1));
    expect(callsTo("PATCH", AGENT)[0][1]).toMatchObject({ body: { status: next } });
  });

  it("duplicates the agent and opens the copy", async () => {
    routes({ [`POST ${AGENT}/duplicate`]: agent({ id: "copy-1", name: "Copy of Math helper" }) });
    renderPage("owner");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/orgs/org-1/agents/copy-1"));
    expect(callsTo("POST", `${AGENT}/duplicate`)[0][1]).toMatchObject({ body: {} });
  });

  it("asks before deleting, then returns to the list", async () => {
    routes({ [`DELETE ${AGENT}`]: undefined });
    renderPage("owner");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(callsTo("DELETE", AGENT)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/orgs/org-1/agents"));
    expect(callsTo("DELETE", AGENT)).toHaveLength(1);
  });

  it("lets you back out of a delete", async () => {
    routes();
    renderPage("owner");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Confirm delete" })).not.toBeInTheDocument();
    expect(callsTo("DELETE", AGENT)).toHaveLength(0);
  });

  it("shows the API's reason when an action is refused", async () => {
    routes({
      [`PATCH ${AGENT}`]: apiError(403, "forbidden", "You do not have permission to do that."),
    });
    renderPage("owner");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Disable" }));
    expect(await screen.findByText("You do not have permission to do that.")).toBeInTheDocument();
  });

  it("shows a not-found page for a missing agent", async () => {
    routeApi({ [`GET ${AGENT}`]: apiError(404, "agent_not_found", "Agent not found.") });
    renderPage("owner");
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to agents" })).toHaveAttribute(
      "href",
      "/orgs/org-1/agents",
    );
  });
});

describe("version history", () => {
  const rowFor = (n: number) => screen.getByText(`Version ${n}`).closest("li") as HTMLElement;

  it("lists versions newest first, with notes, marking the current one", async () => {
    routes();
    renderPage("owner");
    await screen.findByText("Version 2");
    expect(within(rowFor(2)).getByText("Current")).toBeInTheDocument();
    expect(within(rowFor(2)).getByText("Added the calculator")).toBeInTheDocument();
    expect(within(rowFor(1)).queryByText("Current")).not.toBeInTheDocument();
    expect(within(rowFor(1)).getByText("First draft")).toBeInTheDocument();
    const order = screen
      .getAllByText(/^Version \d+/)
      .map((el) => el.textContent?.match(/^Version (\d+)/)?.[1]);
    expect(order).toEqual(["2", "1"]);
  });

  it("offers Restore only for versions that are not current", async () => {
    routes();
    renderPage("admin");
    await screen.findByText("Version 2");
    expect(within(rowFor(2)).queryByRole("button", { name: /Restore/ })).not.toBeInTheDocument();
    expect(
      within(rowFor(1)).getByRole("button", { name: "Restore version 1" }),
    ).toBeInTheDocument();
  });

  it("restores an older version after confirmation", async () => {
    routes({ [`POST ${AGENT}/rollback`]: agent({ current_version: v1 }) });
    renderPage("owner");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Restore version 1" }));
    expect(callsTo("POST", `${AGENT}/rollback`)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Confirm restore" }));
    await waitFor(() => expect(callsTo("POST", `${AGENT}/rollback`)).toHaveLength(1));
    expect(callsTo("POST", `${AGENT}/rollback`)[0][1]).toMatchObject({ body: { version: 1 } });
  });

  it("lets you cancel a restore", async () => {
    routes();
    renderPage("owner");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Restore version 1" }));
    await user.click(within(rowFor(1)).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("button", { name: "Confirm restore" })).not.toBeInTheDocument();
  });

  it("shows why a restore was refused", async () => {
    routes({
      [`POST ${AGENT}/rollback`]: apiError(
        409,
        "already_current",
        "That version is already the current one.",
      ),
    });
    renderPage("owner");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Restore version 1" }));
    await user.click(screen.getByRole("button", { name: "Confirm restore" }));
    expect(await screen.findByText("That version is already the current one.")).toBeInTheDocument();
  });

  it("loads an old version's settings only when asked to view it", async () => {
    routes({}, agent({ current_version: v2 }));
    renderPage("member");
    const user = userEvent.setup();
    await screen.findByText("Version 1");
    expect(callsTo("GET", `${AGENT}/versions/1`)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "View version 1" }));
    await waitFor(() => expect(callsTo("GET", `${AGENT}/versions/1`)).toHaveLength(1));
    expect(within(rowFor(1)).getByText("You help with maths.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Hide version 1" }));
    expect(within(rowFor(1)).queryByText("You help with maths.")).not.toBeInTheDocument();
  });

  it("loads more versions on request", async () => {
    routes({ [`GET ${AGENT}/versions`]: pageOf([summary(v2), summary(v1)], 45) });
    renderPage("owner");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Show more" }));
    await waitFor(() => {
      const limits = callsTo("GET", `${AGENT}/versions`).map(
        ([, o]) => (o as { query: { limit: number } }).query.limit,
      );
      expect(limits).toContain(40);
    });
  });
});
