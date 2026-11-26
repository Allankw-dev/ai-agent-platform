import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentForm } from "@/features/agents/agent-form";
import {
  emptyFormValues,
  valuesFromAgent,
  type AgentFormValues,
} from "@/features/agents/agent-form-model";
import { apiError, apiFetch, routeApi } from "@/test/api-mock";
import {
  agent,
  CATALOG,
  CATALOG_WITH_HTTP,
  pageOf,
  SLACK_SEND,
  version,
  CALCULATOR,
  HTTP_GET,
} from "@/test/agents";
import type { Integration } from "@/lib/api/types";
import { resetAuth } from "@/test/auth-mock";
import { renderWithQuery } from "@/test/render";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const onSubmit = vi.fn<(values: AgentFormValues) => void>();

function renderForm(props: Partial<React.ComponentProps<typeof AgentForm>> = {}) {
  return renderWithQuery(
    <AgentForm
      mode="create"
      orgId="org-1"
      initial={emptyFormValues()}
      submitLabel="Create agent"
      submittingLabel="Creating…"
      submitting={false}
      error={null}
      cancelHref="/orgs/org-1/agents"
      onSubmit={onSubmit}
      {...props}
    />,
  );
}

beforeEach(() => {
  resetAuth();
  apiFetch.mockReset();
  onSubmit.mockReset();
  routeApi({ "GET /tools": CATALOG });
});

async function fillBasics(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Name"), "Math helper");
  await user.type(screen.getByLabelText("Instructions"), "You help with maths.");
}

describe("AgentForm", () => {
  it("shows the catalog and marks sensitive tools", async () => {
    renderForm();
    expect(await screen.findByRole("checkbox", { name: "Calculator" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Current time" })).toBeInTheDocument();
    const sensitive = screen.getByRole("checkbox", { name: "Send Slack message" });
    expect(
      within(sensitive.closest("li") as HTMLElement).getByText("Sensitive"),
    ).toBeInTheDocument();
  });

  it("only offers an approval switch for tools that are ticked", async () => {
    renderForm();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: "Calculator" }));
    const approval = screen.getByRole("checkbox", { name: "Require approval for Calculator" });
    expect(approval).not.toBeChecked();
    expect(approval).toBeEnabled();
    expect(
      screen.queryByRole("checkbox", { name: "Require approval for Current time" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Calculator" }));
    expect(
      screen.queryByRole("checkbox", { name: "Require approval for Calculator" }),
    ).not.toBeInTheDocument();
  });

  it("always requires approval for a sensitive tool, and says so", async () => {
    renderForm();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: "Send Slack message" }));
    const approval = screen.getByRole("checkbox", {
      name: "Require approval for Send Slack message",
    });
    expect(approval).toBeChecked();
    expect(approval).toBeDisabled();
    expect(screen.getByText("(always, for sensitive tools)")).toBeInTheDocument();
  });

  it("explains that approvals are not available yet", async () => {
    renderForm();
    expect(await screen.findByText(/Approvals are not available yet/)).toBeInTheDocument();
  });

  it("submits the values the user entered", async () => {
    renderForm();
    const user = userEvent.setup();
    await fillBasics(user);
    await user.click(await screen.findByRole("checkbox", { name: "Calculator" }));
    await user.click(screen.getByRole("checkbox", { name: "Require approval for Calculator" }));
    await user.click(screen.getByRole("checkbox", { name: "Send Slack message" }));
    await user.clear(screen.getByLabelText("Model calls per run"));
    await user.type(screen.getByLabelText("Model calls per run"), "4");
    expect(screen.getByLabelText("Tool calls per run")).toHaveValue("20");
    await user.clear(screen.getByLabelText("Tool calls per run"));
    await user.type(screen.getByLabelText("Tool calls per run"), "6");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const values = onSubmit.mock.calls[0][0];
    expect(values).toMatchObject({
      name: "Math helper",
      instructions: "You help with maths.",
      model: "gemini-3-flash-preview",
      maxIterations: "4",
      maxToolCalls: "6",
    });
    expect(values.tools).toEqual([
      { toolKey: "utility.calculate", requiresApproval: true, config: {}, provider: null },
      { toolKey: "slack.send_message", requiresApproval: true, config: {}, provider: null },
    ]);
  });

  it("blocks an invalid form and points at every problem", async () => {
    renderForm();
    const user = userEvent.setup();
    await screen.findByRole("checkbox", { name: "Calculator" });
    await user.clear(screen.getByLabelText("Model"));
    await user.clear(screen.getByLabelText("Model calls per run"));
    await user.type(screen.getByLabelText("Model calls per run"), "99");
    await user.clear(screen.getByLabelText("Tool calls per run"));
    await user.type(screen.getByLabelText("Tool calls per run"), "500");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Fix the highlighted fields and try again.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Use at least 2 characters.");
    expect(screen.getByLabelText("Instructions")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Enter a model name.")).toBeInTheDocument();
    expect(screen.getByText("Use a number from 1 to 25.")).toBeInTheDocument();
    expect(screen.getByText("Use a number from 1 to 100.")).toBeInTheDocument();
  });

  it("suggests models but accepts any valid name", async () => {
    const { container } = renderForm();
    await screen.findByRole("checkbox", { name: "Calculator" });
    const options = Array.from(container.querySelectorAll("#agent-model-suggestions option")).map(
      (o) => o.getAttribute("value"),
    );
    expect(options).toContain("gemini-3-flash-preview");
    expect(options).toContain("gemini-flash-lite-latest");

    const user = userEvent.setup();
    await fillBasics(user);
    await user.clear(screen.getByLabelText("Model"));
    await user.type(screen.getByLabelText("Model"), "gemini-future-model-9");
    await user.click(screen.getByRole("button", { name: "Create agent" }));
    expect(onSubmit.mock.calls[0][0].model).toBe("gemini-future-model-9");
  });

  it("offers only the providers the platform has enabled", () => {
    renderForm();
    const provider = screen.getByLabelText("Provider");
    expect(provider).toBeDisabled();
    expect(
      within(provider)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Gemini"]);
  });

  it("hides the change note when creating and shows it when editing", async () => {
    const { unmount } = renderForm();
    expect(screen.queryByLabelText("What changed? (optional)")).not.toBeInTheDocument();
    unmount();

    renderForm({ mode: "edit", submitLabel: "Save changes" });
    expect(screen.getByLabelText("What changed? (optional)")).toBeInTheDocument();
  });

  it("starts from the agent's saved settings when editing", async () => {
    const saved = agent({
      current_version: version(3, {
        system_instructions: "Be precise.",
        objectives: "Never guess.",
        model_params: { max_output_tokens: 512 },
        limits: {
          max_iterations: 3,
          timeout_seconds: 30,
          max_total_tokens: 9_000,
          cost_budget_usd: 0.5,
        },
        tools: [
          {
            tool_key: "utility.calculate",
            name: "Calculator",
            description: "d",
            provider: null,
            is_sensitive: false,
            requires_approval: true,
            config: {},
          },
        ],
      }),
    });
    renderForm({ mode: "edit", initial: valuesFromAgent(saved), submitLabel: "Save changes" });
    expect(screen.getByLabelText("Name")).toHaveValue("Math helper");
    expect(screen.getByLabelText("Instructions")).toHaveValue("Be precise.");
    expect(screen.getByLabelText("Objectives (optional)")).toHaveValue("Never guess.");
    expect(screen.getByLabelText("Model calls per run")).toHaveValue("3");
    expect(screen.getByLabelText("Cost budget in US dollars (optional)")).toHaveValue("0.5");
    expect(screen.getByLabelText("Maximum reply length in tokens (optional)")).toHaveValue("512");
    expect(await screen.findByRole("checkbox", { name: "Calculator" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Require approval for Calculator" })).toBeChecked();
  });

  it("disables the button while saving and shows the server's error", async () => {
    renderForm({
      submitting: true,
      error: apiError(409, "agent_name_taken", "An agent with that name already exists."),
    });
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(screen.getByText("An agent with that name already exists.")).toBeInTheDocument();
  });

  it("links Cancel back to where the user came from", () => {
    renderForm();
    expect(screen.getByRole("link", { name: "Cancel" })).toHaveAttribute(
      "href",
      "/orgs/org-1/agents",
    );
  });

  it("says so when the tool catalog cannot be loaded", async () => {
    routeApi({ "GET /tools": apiError(500, "boom", "The server had a problem.") });
    renderForm();
    await waitFor(() => expect(screen.getByText("The server had a problem.")).toBeInTheDocument());
  });

  describe("tools that need an integration", () => {
    const stored = (overrides: Partial<Integration>): Integration => ({
      id: "int-1",
      provider: "http",
      name: "Weather API",
      status: "active",
      config: { allowed_hosts: ["api.example.com"] },
      has_credential: true,
      credential_set_by_id: null,
      credential_set_by_name: null,
      credential_updated_at: null,
      created_at: "2026-11-16T00:00:00Z",
      updated_at: "2026-11-16T00:00:00Z",
      ...overrides,
    });
    const LIST = "GET /organizations/org-1/integrations";

    function withIntegrations(items: Integration[]) {
      routeApi({ "GET /tools": CATALOG_WITH_HTTP, [LIST]: pageOf(items) });
    }

    it("does not even ask for integrations when no tool needs one", async () => {
      renderForm();
      await screen.findByRole("checkbox", { name: "Calculator" });
      expect(apiFetch.mock.calls.some(([path]) => String(path).includes("/integrations"))).toBe(
        false,
      );
    });

    it("offers only active integrations of the right type, with what they allow", async () => {
      withIntegrations([
        stored({ id: "int-1", name: "Weather API" }),
        stored({ id: "int-2", name: "Old API", status: "disabled" }),
        stored({ id: "int-3", name: "Team Slack", provider: "slack", config: {} }),
        stored({ id: "int-4", name: "Maps API", config: { allowed_hosts: ["maps.example.com"] } }),
      ]);
      const user = userEvent.setup();
      renderForm();
      await user.click(await screen.findByRole("checkbox", { name: "HTTP GET" }));
      const choice = await screen.findByLabelText("Integration for HTTP GET");
      const names = within(choice)
        .getAllByRole("option")
        .map((option) => option.textContent);
      expect(names).toEqual(["Choose an integration…", "Weather API", "Maps API"]);
      await user.selectOptions(choice, "int-4");
      expect(screen.getByText("Allowed hosts: maps.example.com")).toBeInTheDocument();
    });

    it("chooses the integration for you when only one fits", async () => {
      withIntegrations([stored({})]);
      const user = userEvent.setup();
      renderForm();
      await screen.findByRole("checkbox", { name: "HTTP GET" });
      await user.click(screen.getByRole("checkbox", { name: "HTTP GET" }));
      const choice = await screen.findByLabelText("Integration for HTTP GET");
      await waitFor(() => expect(choice).toHaveValue("int-1"));
      await fillBasics(user);
      await user.click(screen.getByRole("button", { name: "Create agent" }));
      expect(onSubmit.mock.calls[0]?.[0].tools).toEqual([
        {
          toolKey: "http.get",
          requiresApproval: false,
          config: { integration_id: "int-1" },
          provider: "http",
        },
      ]);
    });

    it("blocks saving until an integration is chosen when there are several", async () => {
      withIntegrations([stored({ id: "int-1" }), stored({ id: "int-2", name: "Maps API" })]);
      const user = userEvent.setup();
      renderForm();
      await screen.findByRole("checkbox", { name: "HTTP GET" });
      await user.click(screen.getByRole("checkbox", { name: "HTTP GET" }));
      const choice = await screen.findByLabelText("Integration for HTTP GET");
      expect(choice).toHaveValue("");
      await fillBasics(user);
      await user.click(screen.getByRole("button", { name: "Create agent" }));
      expect(await screen.findByText(/Choose an integration for each tool/)).toBeInTheDocument();
      expect(onSubmit).not.toHaveBeenCalled();

      await user.selectOptions(choice, "int-2");
      await user.click(screen.getByRole("button", { name: "Create agent" }));
      expect(onSubmit.mock.calls[0]?.[0].tools[0]?.config).toEqual({ integration_id: "int-2" });
    });

    it("points to the Integrations tab when there is nothing to choose", async () => {
      withIntegrations([stored({ id: "int-3", provider: "slack", config: {} })]);
      const user = userEvent.setup();
      renderForm();
      await screen.findByRole("checkbox", { name: "HTTP GET" });
      await user.click(screen.getByRole("checkbox", { name: "HTTP GET" }));
      expect(await screen.findByText(/No active HTTP \/ API integration yet/)).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Integrations tab" })).toHaveAttribute(
        "href",
        "/orgs/org-1/integrations",
      );
      await fillBasics(user);
      await user.click(screen.getByRole("button", { name: "Create agent" }));
      expect(onSubmit).not.toHaveBeenCalled();
    });

    it("warns when an agent's chosen integration has since been disabled or deleted", async () => {
      withIntegrations([stored({ id: "int-1", status: "disabled" })]);
      const saved = agent({
        current_version: version(2, {
          tools: [
            {
              tool_key: "http.get",
              name: "HTTP GET",
              description: "d",
              provider: "http",
              is_sensitive: false,
              requires_approval: false,
              config: { integration_id: "int-1" },
            },
          ],
        }),
      });
      renderForm({ mode: "edit", initial: valuesFromAgent(saved), submitLabel: "Save changes" });
      expect(await screen.findByText(/chosen earlier is disabled or deleted/)).toBeInTheDocument();
    });

    it("offers Slack integrations for the Slack tool, with their allowed channels", async () => {
      routeApi({
        "GET /tools": [CALCULATOR, HTTP_GET, SLACK_SEND],
        [LIST]: pageOf([
          stored({ id: "int-1", name: "Weather API" }),
          stored({
            id: "int-5",
            provider: "slack",
            name: "Team Slack",
            config: { allowed_channels: ["C0123456789"] },
          }),
          stored({
            id: "int-6",
            provider: "slack",
            name: "Ops Slack",
            config: { allowed_channels: ["C0999999999", "G0888888888"] },
          }),
        ]),
      });
      const user = userEvent.setup();
      renderForm();
      await user.click(await screen.findByRole("checkbox", { name: "Send Slack message" }));
      const choice = await screen.findByLabelText("Integration for Send Slack message");
      expect(
        within(choice)
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Choose an integration…", "Team Slack", "Ops Slack"]);
      await user.selectOptions(choice, "int-6");
      expect(screen.getByText("Allowed channels: C0999999999, G0888888888")).toBeInTheDocument();
      const approval = screen.getByRole("checkbox", {
        name: "Require approval for Send Slack message",
      });
      expect(approval).toBeChecked();
      expect(approval).toBeDisabled();
    });

    it("keeps the approval switch locked on for the write tool", async () => {
      withIntegrations([stored({})]);
      const user = userEvent.setup();
      renderForm();
      await screen.findByRole("checkbox", { name: "HTTP request (changes data)" });
      await user.click(screen.getByRole("checkbox", { name: "HTTP request (changes data)" }));
      const approval = await screen.findByRole("checkbox", {
        name: "Require approval for HTTP request (changes data)",
      });
      expect(approval).toBeChecked();
      expect(approval).toBeDisabled();
    });
  });
});
