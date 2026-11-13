import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentsListPage } from "@/features/agents/agents-list-page";
import type { OrgRole } from "@/lib/api/types";
import { agent, inOrg, listItem, pageOf, version } from "@/test/agents";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { resetNavigation } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const LIST = "GET /organizations/org-1/agents";
const renderList = (role: OrgRole) => renderWithQuery(inOrg(role, <AgentsListPage />));
const queriesSent = () =>
  callsTo("GET", "/organizations/org-1/agents").map(
    ([, options]) => (options as { query: Record<string, unknown> }).query,
  );

const ITEMS = [
  listItem(agent({ id: "a-1", name: "Support triage", status: "active" })),
  listItem(
    agent({
      id: "a-2",
      name: "Report writer",
      description: null,
      status: "draft",
      current_version: version(1, { model: "gemini-flash-lite-latest" }),
    }),
  ),
];

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
});

describe("AgentsListPage", () => {
  it("lists agents with status, version, model and a link to each", async () => {
    routeApi({ [LIST]: pageOf(ITEMS) });
    renderList("owner");
    const link = await screen.findByRole("link", { name: "Support triage" });
    expect(link).toHaveAttribute("href", "/orgs/org-1/agents/a-1");
    const row = link.closest("li") as HTMLElement;
    expect(within(row).getByText("Active")).toBeInTheDocument();
    expect(within(row).getByText("Answers arithmetic questions.")).toBeInTheDocument();
    expect(within(row).getByText(/v2 · gemini-3-flash-preview/)).toBeInTheDocument();

    const second = screen.getByRole("link", { name: "Report writer" }).closest("li") as HTMLElement;
    expect(within(second).getByText("Draft")).toBeInTheDocument();
    expect(within(second).getByText(/v1 · gemini-flash-lite-latest/)).toBeInTheDocument();
    expect(screen.getByText("2 agents.")).toBeInTheDocument();
  });

  it.each([
    ["owner", true],
    ["admin", true],
    ["developer", true],
    ["member", false],
  ] as const)("%s sees the Create button: %s", async (role, shown) => {
    routeApi({ [LIST]: pageOf(ITEMS) });
    renderList(role);
    await screen.findByText("Support triage");
    const button = screen.queryByRole("link", { name: "Create agent" });
    if (shown) expect(button).toHaveAttribute("href", "/orgs/org-1/agents/new");
    else expect(button).not.toBeInTheDocument();
  });

  it("invites managers to create the first agent", async () => {
    routeApi({ [LIST]: pageOf([]) });
    renderList("developer");
    expect(await screen.findByText("No agents yet")).toBeInTheDocument();
    expect(screen.getByText("Create your first agent to get started.")).toBeInTheDocument();
  });

  it("tells members who to ask when there are no agents", async () => {
    routeApi({ [LIST]: pageOf([]) });
    renderList("member");
    expect(
      await screen.findByText("Ask an owner, admin or developer to create one."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create agent" })).not.toBeInTheDocument();
  });

  it("filters by status through the API", async () => {
    routeApi({
      [LIST]: ({ query }: { query?: Record<string, unknown> }) =>
        pageOf(query?.status === "draft" ? [ITEMS[1]] : ITEMS),
    });
    renderList("owner");
    await screen.findByText("Support triage");
    await userEvent.setup().selectOptions(screen.getByLabelText("Filter by status"), "draft");

    await waitFor(() => expect(screen.queryByText("Support triage")).not.toBeInTheDocument());
    expect(screen.getByText("Report writer")).toBeInTheDocument();
    expect(queriesSent().at(-1)).toMatchObject({ status: "draft", limit: 20 });
    expect(screen.getByText("1 agent match.")).toBeInTheDocument();
  });

  it("searches by name when the form is submitted, not on every keystroke", async () => {
    routeApi({
      [LIST]: ({ query }: { query?: Record<string, unknown> }) =>
        pageOf(query?.q ? [ITEMS[0]] : ITEMS),
    });
    renderList("owner");
    await screen.findByText("Report writer");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Search agents by name"), "support");
    expect(queriesSent().some((q) => q.q === "support")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(screen.queryByText("Report writer")).not.toBeInTheDocument());
    expect(queriesSent().at(-1)).toMatchObject({ q: "support" });
  });

  it("explains an empty result when filtering, and can clear the filters", async () => {
    routeApi({
      [LIST]: ({ query }: { query?: Record<string, unknown> }) =>
        pageOf(query?.status === "disabled" ? [] : ITEMS),
    });
    renderList("member");
    await screen.findByText("Support triage");
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter by status"), "disabled");
    expect(await screen.findByText("No agents match")).toBeInTheDocument();
    expect(screen.queryByText("Create your first agent to get started.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("Support triage")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by status")).toHaveValue("");
  });

  it("loads more when there are more agents than shown", async () => {
    routeApi({ [LIST]: pageOf(ITEMS, 45) });
    renderList("owner");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Show more" }));
    await waitFor(() => expect(queriesSent().map((q) => q.limit)).toContain(40));
  });

  it("shows the API's error", async () => {
    routeApi({ [LIST]: apiError(500, "boom", "The server had a problem.") });
    renderList("owner");
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});
