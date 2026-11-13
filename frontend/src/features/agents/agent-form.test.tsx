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
import { agent, CATALOG, version } from "@/test/agents";
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
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const values = onSubmit.mock.calls[0][0];
    expect(values).toMatchObject({
      name: "Math helper",
      instructions: "You help with maths.",
      model: "gemini-3-flash-preview",
      maxIterations: "4",
    });
    expect(values.tools).toEqual([
      { toolKey: "utility.calculate", requiresApproval: true, config: {} },
      { toolKey: "slack.send_message", requiresApproval: true, config: {} },
    ]);
  });

  it("blocks an invalid form and points at every problem", async () => {
    renderForm();
    const user = userEvent.setup();
    await screen.findByRole("checkbox", { name: "Calculator" });
    await user.clear(screen.getByLabelText("Model"));
    await user.clear(screen.getByLabelText("Model calls per run"));
    await user.type(screen.getByLabelText("Model calls per run"), "99");
    await user.click(screen.getByRole("button", { name: "Create agent" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("Fix the highlighted fields and try again.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Use at least 2 characters.");
    expect(screen.getByLabelText("Instructions")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Enter a model name.")).toBeInTheDocument();
    expect(screen.getByText("Use a number from 1 to 25.")).toBeInTheDocument();
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
});
