import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunDetailPage } from "@/features/runs/run-detail-page";
import type { OrgRole } from "@/lib/api/types";
import { inOrg } from "@/test/agents";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation, router } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";
import { run, runDetail } from "@/test/runs";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const RUN = "/organizations/org-1/runs/run-1";
const renderRun = (role: OrgRole = "developer") => renderWithQuery(inOrg(role, <RunDetailPage />));

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  nav.params = { orgId: "org-1", runId: "run-1" };
});
afterEach(() => vi.useRealTimers());

describe("RunDetailPage", () => {
  it("shows a finished run: who ran, the message, the answer, usage and steps", async () => {
    routeApi({ [`GET ${RUN}`]: runDetail() });
    renderRun();
    const heading = await screen.findByRole("heading", { name: /Run of/ });
    expect(within(heading).getByRole("link", { name: "Business helper" })).toHaveAttribute(
      "href",
      "/orgs/org-1/agents/agent-1",
    );
    expect(within(heading.parentElement as HTMLElement).getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText(/Version 2 · started/)).toBeInTheDocument();
    expect(screen.getByText("What is 16% VAT on KES 12,500?")).toBeInTheDocument();
    expect(screen.getByText("VAT is KES 2,000, so the total is KES 14,500.")).toBeInTheDocument();
    expect(screen.getByText("700")).toBeInTheDocument();
    expect(screen.getByText("150")).toBeInTheDocument();
    expect(screen.getByText("Not estimated")).toBeInTheDocument();
    expect(screen.getByText("3.0 s")).toBeInTheDocument();
    expect(screen.getByText("Steps (3)")).toBeInTheDocument();
    expect(screen.getByText("Asked to use: utility_calculate")).toBeInTheDocument();
  });

  it("shows the estimated cost when the server could price it", async () => {
    routeApi({ [`GET ${RUN}`]: runDetail({ cost_usd: 0.0123 }) });
    renderRun();
    expect(await screen.findByText("$0.01")).toBeInTheDocument();
  });

  it("explains a failure and keeps the agent's last reply", async () => {
    routeApi({
      [`GET ${RUN}`]: runDetail({
        status: "failed",
        error: "Stopped: the agent reached its limit of 2 model calls.",
        output: { text: "Partial answer so far" },
      }),
    });
    renderRun();
    expect(
      await screen.findByText("Stopped: the agent reached its limit of 2 model calls."),
    ).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("The agent's last reply:")).toBeInTheDocument();
    expect(screen.getByText("Partial answer so far")).toBeInTheDocument();
  });

  it("says when a run was cancelled", async () => {
    routeApi({ [`GET ${RUN}`]: runDetail({ status: "cancelled", output: null, steps: [] }) });
    renderRun();
    expect(
      await screen.findByText("This run was cancelled before it finished."),
    ).toBeInTheDocument();
  });

  it.each([
    ["queued", /Waiting for a worker to pick this up/],
    ["running", /The agent is working/],
  ] as const)("a %s run says what is happening", async (status, text) => {
    routeApi({ [`GET ${RUN}`]: runDetail({ status, output: null, steps: [], finished_at: null }) });
    renderRun();
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(screen.getByText("This page updates by itself.")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
  });

  it("updates by itself until the run has finished, then stops asking", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let calls = 0;
    routeApi({
      [`GET ${RUN}`]: () => {
        calls += 1;
        return calls < 3
          ? runDetail({ status: "running", output: null, steps: [], finished_at: null })
          : runDetail();
      },
    });
    renderRun();
    expect(await screen.findByText(/The agent is working/)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(4_300);
    expect(
      await screen.findByText("VAT is KES 2,000, so the total is KES 14,500."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/The agent is working/)).not.toBeInTheDocument();
    expect(calls).toBe(3);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls).toBe(3);
  });

  it("lets a manager cancel a run that is still going", async () => {
    routeApi({
      [`GET ${RUN}`]: runDetail({ status: "running", output: null, steps: [], finished_at: null }),
      [`POST ${RUN}/cancel`]: run({ status: "cancelled" }),
    });
    renderRun("developer");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Cancel run" }));
    await waitFor(() => expect(callsTo("POST", `${RUN}/cancel`)).toHaveLength(1));
    expect(screen.queryByRole("button", { name: "Run again" })).not.toBeInTheDocument();
  });

  it("shows why a cancel was refused", async () => {
    routeApi({
      [`GET ${RUN}`]: runDetail({ status: "running", output: null, steps: [], finished_at: null }),
      [`POST ${RUN}/cancel`]: apiError(
        409,
        "run_not_cancellable",
        "This run has already finished.",
      ),
    });
    renderRun();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(await screen.findByText("This run has already finished.")).toBeInTheDocument();
  });

  it("starts the same message again and opens the new run", async () => {
    routeApi({
      [`GET ${RUN}`]: runDetail(),
      "POST /organizations/org-1/agents/agent-1/runs": run({ id: "run-2", status: "queued" }),
    });
    renderRun();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Run again" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/orgs/org-1/runs/run-2"));
    const [, options] = callsTo("POST", "/organizations/org-1/agents/agent-1/runs")[0];
    expect(options).toMatchObject({ body: { message: "What is 16% VAT on KES 12,500?" } });
    expect((options as { headers: Record<string, string> }).headers["Idempotency-Key"]).toEqual(
      expect.any(String),
    );
  });

  it("shows why Run again was refused", async () => {
    routeApi({
      [`GET ${RUN}`]: runDetail(),
      "POST /organizations/org-1/agents/agent-1/runs": apiError(
        409,
        "agent_not_runnable",
        "Only draft or active agents can be run.",
      ),
    });
    renderRun();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Run again" }));
    expect(await screen.findByText("Only draft or active agents can be run.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("lets members watch but not control a run", async () => {
    routeApi({ [`GET ${RUN}`]: runDetail() });
    renderRun("member");
    await screen.findByText("Steps (3)");
    expect(screen.queryByRole("button", { name: "Run again" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
    expect(screen.getByText("Steps (3)")).toBeInTheDocument();
  });

  it("members cannot cancel an active run either", async () => {
    routeApi({
      [`GET ${RUN}`]: runDetail({ status: "running", output: null, steps: [], finished_at: null }),
    });
    renderRun("member");
    await screen.findByText(/The agent is working/);
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });

  it("shows a not-found page for a run that is not in this organization", async () => {
    routeApi({ [`GET ${RUN}`]: apiError(404, "run_not_found", "Run not found.") });
    renderRun();
    expect(await screen.findByText("Run not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to runs" })).toHaveAttribute(
      "href",
      "/orgs/org-1/runs",
    );
  });

  it("shows other errors as they are", async () => {
    routeApi({ [`GET ${RUN}`]: apiError(500, "boom", "The server had a problem.") });
    renderRun();
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});
