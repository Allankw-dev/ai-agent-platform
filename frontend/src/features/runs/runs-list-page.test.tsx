import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunsListPage } from "@/features/runs/runs-list-page";
import { agent, inOrg, listItem, pageOf } from "@/test/agents";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";
import { run } from "@/test/runs";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const RUNS = "/organizations/org-1/runs";
const AGENTS = "GET /organizations/org-1/agents";
const AGENT_LIST = pageOf([
  listItem(agent({ id: "agent-1", name: "Business helper" })),
  listItem(agent({ id: "agent-2", name: "Report writer" })),
]);
type Call = { query?: Record<string, unknown> };
const runQueries = () =>
  callsTo("GET", RUNS).map(([, options]) => (options as { query: Record<string, unknown> }).query);

const RUN_LIST = [
  run({ id: "r-1", cost_usd: 0.007 }),
  run({
    id: "r-2",
    agent_id: "agent-2",
    agent_name: "Report writer",
    agent_version: 1,
    status: "failed",
    input: { message: "Write the weekly report" },
    error: "The model 'x' is overloaded right now (HTTP 503).",
    input_tokens: 0,
    output_tokens: 0,
    started_at: null,
    finished_at: null,
  }),
];

function renderList(role: "owner" | "member" = "owner") {
  return renderWithQuery(inOrg(role, <RunsListPage />));
}

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
});
afterEach(() => vi.useRealTimers());

describe("RunsListPage", () => {
  it("lists runs with agent, version, status, message, usage and a link", async () => {
    routeApi({ [`GET ${RUNS}`]: pageOf(RUN_LIST), [AGENTS]: AGENT_LIST });
    renderList();
    const link = await screen.findByRole("link", { name: "Business helper" });
    expect(link).toHaveAttribute("href", "/orgs/org-1/runs/r-1");
    const first = link.closest("li") as HTMLElement;
    expect(within(first).getByText("v2")).toBeInTheDocument();
    expect(within(first).getByText("Succeeded")).toBeInTheDocument();
    expect(within(first).getByText("What is 16% VAT on KES 12,500?")).toBeInTheDocument();
    expect(within(first).getByText("3.0 s · 850 tokens · cost: $0.0070")).toBeInTheDocument();

    const second = screen.getByRole("link", { name: "Report writer" }).closest("li") as HTMLElement;
    expect(within(second).getByText("Failed")).toBeInTheDocument();
    expect(within(second).getByText("0 tokens · cost: –")).toBeInTheDocument();
    expect(screen.getByText("2 runs, newest first.")).toBeInTheDocument();
  });

  it("does not claim a cost it cannot estimate", async () => {
    routeApi({ [`GET ${RUNS}`]: pageOf([run({ cost_usd: 0 })]), [AGENTS]: AGENT_LIST });
    renderList();
    expect(await screen.findByText(/cost: Not estimated/)).toBeInTheDocument();
  });

  it("filters by status through the API", async () => {
    routeApi({
      [`GET ${RUNS}`]: ({ query }: Call) =>
        pageOf(query?.status === "failed" ? [RUN_LIST[1]] : RUN_LIST),
      [AGENTS]: AGENT_LIST,
    });
    renderList();
    await screen.findByText("What is 16% VAT on KES 12,500?");
    await userEvent.setup().selectOptions(screen.getByLabelText("Filter by status"), "failed");
    await waitFor(() =>
      expect(screen.queryByText("What is 16% VAT on KES 12,500?")).not.toBeInTheDocument(),
    );
    expect(runQueries().at(-1)).toMatchObject({ status: "failed", limit: 20 });
    expect(screen.getByText("1 run match, newest first.")).toBeInTheDocument();
  });

  it("filters by agent, choosing from the organization's agents", async () => {
    routeApi({
      [`GET ${RUNS}`]: ({ query }: Call) =>
        pageOf(query?.agent_id === "agent-2" ? [RUN_LIST[1]] : RUN_LIST),
      [AGENTS]: AGENT_LIST,
    });
    renderList();
    await screen.findByText("Write the weekly report");
    const select = screen.getByLabelText("Filter by agent");
    await waitFor(() => expect(within(select).getByText("Report writer")).toBeInTheDocument());
    await userEvent.setup().selectOptions(select, "agent-2");
    await waitFor(() => expect(runQueries().at(-1)).toMatchObject({ agent_id: "agent-2" }));
  });

  it("starts filtered when opened from an agent's page", async () => {
    nav.search = new URLSearchParams("agent=agent-2");
    routeApi({ [`GET ${RUNS}`]: pageOf([RUN_LIST[1]]), [AGENTS]: AGENT_LIST });
    renderList();
    await screen.findByText("Write the weekly report");
    expect(runQueries()[0]).toMatchObject({ agent_id: "agent-2" });
    await waitFor(() => expect(screen.getByLabelText("Filter by agent")).toHaveValue("agent-2"));
  });

  it("still filters when the agent in the link is not in the first 100", async () => {
    nav.search = new URLSearchParams("agent=agent-77");
    routeApi({ [`GET ${RUNS}`]: pageOf([]), [AGENTS]: AGENT_LIST });
    renderList();
    await screen.findByText("No runs match");
    expect(screen.getByLabelText("Filter by agent")).toHaveValue("agent-77");
  });

  it("explains an empty list, and clears filters", async () => {
    routeApi({
      [`GET ${RUNS}`]: ({ query }: Call) => pageOf(query?.status ? [] : RUN_LIST),
      [AGENTS]: AGENT_LIST,
    });
    renderList("member");
    await screen.findByRole("link", { name: "Business helper" });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Filter by status"), "cancelled");
    expect(await screen.findByText("No runs match")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("link", { name: "Business helper" })).toBeInTheDocument();
  });

  it("points to an agent when there are no runs at all", async () => {
    routeApi({ [`GET ${RUNS}`]: pageOf([]), [AGENTS]: AGENT_LIST });
    renderList();
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.getByText(/use “Run this agent” to start one/)).toBeInTheDocument();
  });

  it("loads more", async () => {
    routeApi({ [`GET ${RUNS}`]: pageOf(RUN_LIST, 45), [AGENTS]: AGENT_LIST });
    renderList();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Show more" }));
    await waitFor(() => expect(runQueries().map((q) => q.limit)).toContain(40));
  });

  it("shows the API's error", async () => {
    routeApi({
      [`GET ${RUNS}`]: apiError(500, "boom", "The server had a problem."),
      [AGENTS]: AGENT_LIST,
    });
    renderList();
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });

  it("keeps refreshing while a run is still going, and stops when all are done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    routeApi({
      [`GET ${RUNS}`]: () => {
        calls += 1;
        return pageOf([run({ status: calls < 2 ? "running" : "succeeded" })]);
      },
      [AGENTS]: AGENT_LIST,
    });
    renderList();
    const list = async () => within(await screen.findByRole("list"));
    expect((await list()).getByText("Running")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(5_200);
    await waitFor(async () => expect((await list()).getByText("Succeeded")).toBeInTheDocument());
    const settled = calls;
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls).toBe(settled);
  });
});
