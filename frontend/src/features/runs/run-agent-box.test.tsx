import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunAgentBox } from "@/features/runs/run-agent-box";
import type { AgentStatus, OrgRole } from "@/lib/api/types";
import { inOrg } from "@/test/agents";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { resetNavigation, router } from "@/test/next-navigation";
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

const START = "/organizations/org-1/agents/agent-1/runs";

function renderBox(role: OrgRole = "developer", status: AgentStatus = "active") {
  return renderWithQuery(
    inOrg(role, <RunAgentBox agentId="agent-1" status={status} version={2} />),
  );
}
const keyOf = (index: number) =>
  (callsTo("POST", START)[index][1] as { headers: Record<string, string> }).headers[
    "Idempotency-Key"
  ];

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
});

describe("RunAgentBox", () => {
  it("starts a run with the message and opens its page", async () => {
    routeApi({ [`POST ${START}`]: run({ id: "run-9", status: "queued" }) });
    renderBox();
    const user = userEvent.setup();
    expect(screen.getByText(/current version \(version 2\)/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "What is 2 + 2?");
    await user.click(screen.getByRole("button", { name: "Run agent" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/orgs/org-1/runs/run-9"));
    expect(callsTo("POST", START)).toHaveLength(1);
    expect(callsTo("POST", START)[0][1]).toMatchObject({ body: { message: "What is 2 + 2?" } });
    expect(keyOf(0)).toEqual(expect.any(String));
    expect(keyOf(0).length).toBeGreaterThanOrEqual(8);
  });

  it("works for a draft agent too, so it can be tested before it is activated", async () => {
    renderBox("owner", "draft");
    expect(screen.getByRole("button", { name: "Run agent" })).toBeInTheDocument();
  });

  it("will not send a blank message", async () => {
    routeApi({});
    renderBox();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "   ");
    await user.click(screen.getByRole("button", { name: "Run agent" }));
    expect(screen.getByText("Write a message for the agent.")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("will not send a message over the limit", async () => {
    routeApi({});
    renderBox();
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "x".repeat(20_001) } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Run agent" }));
    expect(screen.getByText("Use at most 20,000 characters.")).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows why the platform refused and stays on the page", async () => {
    routeApi({
      [`POST ${START}`]: apiError(
        503,
        "ai_not_configured",
        "The gemini provider is not configured on this platform.",
      ),
    });
    renderBox();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "Hello");
    await user.click(screen.getByRole("button", { name: "Run agent" }));
    expect(
      await screen.findByText("The gemini provider is not configured on this platform."),
    ).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Run agent" })).toBeEnabled();
  });

  it("reuses the same key when the same message is retried, and a new key for a new message", async () => {
    routeApi({
      [`POST ${START}`]: apiError(
        503,
        "queue_unavailable",
        "The run could not be queued. Try again.",
      ),
    });
    renderBox();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "Hello");
    await user.click(screen.getByRole("button", { name: "Run agent" }));
    await screen.findByText("The run could not be queued. Try again.");
    await user.click(screen.getByRole("button", { name: "Run agent" }));
    await waitFor(() => expect(callsTo("POST", START)).toHaveLength(2));
    expect(keyOf(1)).toBe(keyOf(0));

    await user.type(screen.getByLabelText("Message"), " please");
    await user.click(screen.getByRole("button", { name: "Run agent" }));
    await waitFor(() => expect(callsTo("POST", START)).toHaveLength(3));
    expect(keyOf(2)).not.toBe(keyOf(0));
  });

  it("explains instead of offering a form when the agent is disabled", () => {
    renderBox("owner", "disabled");
    expect(screen.getByText("This agent is disabled. Enable it to run it.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();
  });

  it("explains to members that they can watch but not run", () => {
    renderBox("member");
    expect(
      screen.getByText(/Only owners, admins and developers can run agents/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Message")).not.toBeInTheDocument();
  });
});
