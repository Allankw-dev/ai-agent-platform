import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentCreatePage } from "@/features/agents/agent-create-page";
import { agent, CATALOG, inOrg } from "@/test/agents";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
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

const CREATE = "/organizations/org-1/agents";

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
});

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Name"), "  Math helper  ");
  await user.type(screen.getByLabelText("Description (optional)"), "Does sums.");
  await user.type(screen.getByLabelText("Instructions"), "You help with maths.");
  await user.click(await screen.findByRole("checkbox", { name: "Calculator" }));
  await user.click(screen.getByRole("button", { name: "Create agent" }));
}

describe("AgentCreatePage", () => {
  it("creates the agent through the API and opens it", async () => {
    routeApi({
      "GET /tools": CATALOG,
      [`POST ${CREATE}`]: agent({ id: "new-agent" }),
    });
    renderWithQuery(inOrg("developer", <AgentCreatePage />));
    await fillAndSubmit();

    await waitFor(() => expect(callsTo("POST", CREATE)).toHaveLength(1));
    expect(callsTo("POST", CREATE)[0][1]).toMatchObject({
      body: {
        name: "Math helper",
        description: "Does sums.",
        config: {
          provider: "gemini",
          model: "gemini-3-flash-preview",
          system_instructions: "You help with maths.",
          objectives: null,
          model_params: { max_output_tokens: null },
          limits: {
            max_iterations: 10,
            timeout_seconds: 120,
            max_total_tokens: 50_000,
            cost_budget_usd: null,
          },
          tools: [{ tool_key: "utility.calculate", requires_approval: false, config: {} }],
        },
      },
    });
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/orgs/org-1/agents/new-agent"));
  });

  it("shows the API's reason and stays on the form when the name is taken", async () => {
    routeApi({
      "GET /tools": CATALOG,
      [`POST ${CREATE}`]: apiError(
        409,
        "agent_name_taken",
        "An agent with that name already exists.",
      ),
    });
    renderWithQuery(inOrg("owner", <AgentCreatePage />));
    await fillAndSubmit();
    expect(await screen.findByText("An agent with that name already exists.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Name")).toHaveValue("  Math helper  ");
  });

  it("does not call the API when the form is invalid", async () => {
    routeApi({ "GET /tools": CATALOG });
    renderWithQuery(inOrg("owner", <AgentCreatePage />));
    await userEvent.setup().click(await screen.findByRole("button", { name: "Create agent" }));
    expect(callsTo("POST", CREATE)).toHaveLength(0);
    expect(screen.getByText("Fix the highlighted fields and try again.")).toBeInTheDocument();
  });

  it("shows members an explanation instead of the form", () => {
    routeApi({});
    renderWithQuery(inOrg("member", <AgentCreatePage />));
    expect(screen.getByText("You can view agents but not change them")).toBeInTheDocument();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to agents" })).toHaveAttribute(
      "href",
      "/orgs/org-1/agents",
    );
    expect(apiFetch).not.toHaveBeenCalled();
  });
});
