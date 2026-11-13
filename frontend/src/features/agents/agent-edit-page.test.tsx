import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentEditPage } from "@/features/agents/agent-edit-page";
import type { OrgRole } from "@/lib/api/types";
import { agent, CATALOG, inOrg, version } from "@/test/agents";
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
const saved = agent({
  current_version: version(2, {
    model_params: { max_output_tokens: 512 },
    tools: [
      {
        tool_key: "utility.calculate",
        name: "Calculator",
        description: "d",
        is_sensitive: false,
        requires_approval: false,
        config: { precision: 2 },
      },
    ],
  }),
});

function routes(overrides: Record<string, unknown> = {}) {
  routeApi({ "GET /tools": CATALOG, [`GET ${AGENT}`]: saved, ...overrides });
}
const renderEdit = (role: OrgRole = "developer") => renderWithQuery(inOrg(role, <AgentEditPage />));
const posted = () => callsTo("POST", `${AGENT}/versions`);
const patched = () => callsTo("PATCH", AGENT);

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  nav.params = { orgId: "org-1", agentId: "agent-1" };
});

async function openForm() {
  const user = userEvent.setup();
  await screen.findByRole("heading", { name: "Edit Math helper" });
  await screen.findByRole("checkbox", { name: "Calculator" });
  return user;
}

describe("AgentEditPage", () => {
  it("starts from what the agent currently is", async () => {
    routes();
    renderEdit();
    await openForm();
    expect(screen.getByLabelText("Name")).toHaveValue("Math helper");
    expect(screen.getByLabelText("Instructions")).toHaveValue("You help with maths.");
    expect(screen.getByRole("checkbox", { name: "Calculator" })).toBeChecked();
  });

  it("does not call the API when nothing changed", async () => {
    routes();
    renderEdit();
    const user = await openForm();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText("Nothing to save: you have not changed anything."),
    ).toBeInTheDocument();
    expect(posted()).toHaveLength(0);
    expect(patched()).toHaveLength(0);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("saves changed behavior as a new version, with the change note", async () => {
    routes({ [`POST ${AGENT}/versions`]: version(3) });
    renderEdit();
    const user = await openForm();
    await user.type(screen.getByLabelText("Instructions"), " Show your working.");
    await user.type(screen.getByLabelText("What changed? (optional)"), "Ask for working");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(posted()).toHaveLength(1));
    expect(posted()[0][1]).toMatchObject({
      body: {
        change_note: "Ask for working",
        config: {
          system_instructions: "You help with maths. Show your working.",
          model: "gemini-3-flash-preview",
          model_params: { max_output_tokens: 512 },
          // Per-tool settings the form does not edit are carried over, not lost.
          tools: [
            { tool_key: "utility.calculate", requires_approval: false, config: { precision: 2 } },
          ],
        },
      },
    });
    expect(patched()).toHaveLength(0);
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/orgs/org-1/agents/agent-1"));
  });

  it("only updates the agent when just the name changed", async () => {
    routes({ [`PATCH ${AGENT}`]: agent({ name: "Calculator bot" }) });
    renderEdit();
    const user = await openForm();
    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Calculator bot");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patched()).toHaveLength(1));
    expect(patched()[0][1]).toMatchObject({ body: { name: "Calculator bot" } });
    expect((patched()[0][1] as { body: object }).body).not.toHaveProperty("description");
    expect(posted()).toHaveLength(0);
    await waitFor(() => expect(router.push).toHaveBeenCalled());
  });

  it("clears the description when it is emptied", async () => {
    routes({ [`PATCH ${AGENT}`]: agent({ description: null }) });
    renderEdit();
    const user = await openForm();
    await user.clear(screen.getByLabelText("Description (optional)"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(patched()).toHaveLength(1));
    expect(patched()[0][1]).toMatchObject({ body: { description: null } });
  });

  it("does the version first and then the rename when both changed", async () => {
    const order: string[] = [];
    routes({
      [`POST ${AGENT}/versions`]: () => {
        order.push("version");
        return version(3);
      },
      [`PATCH ${AGENT}`]: () => {
        order.push("rename");
        return agent({ name: "Renamed" });
      },
    });
    renderEdit();
    const user = await openForm();
    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Renamed");
    await user.click(screen.getByRole("checkbox", { name: "Current time" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(router.push).toHaveBeenCalled());
    expect(order).toEqual(["version", "rename"]);
  });

  it("says plainly when the version was saved but the rename was refused", async () => {
    routes({
      [`POST ${AGENT}/versions`]: version(3),
      [`PATCH ${AGENT}`]: apiError(
        409,
        "agent_name_taken",
        "An agent with that name already exists.",
      ),
    });
    renderEdit();
    const user = await openForm();
    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Taken");
    await user.click(screen.getByRole("checkbox", { name: "Current time" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(
      await screen.findByText(
        "The new version was saved, but the name or description was not: An agent with that name already exists.",
      ),
    ).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("does not rename when saving the version failed", async () => {
    routes({
      [`POST ${AGENT}/versions`]: apiError(
        422,
        "unknown_tool",
        "Unknown tool: utility.current_time.",
      ),
    });
    renderEdit();
    const user = await openForm();
    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "Renamed");
    await user.click(screen.getByRole("checkbox", { name: "Current time" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Unknown tool: utility.current_time.")).toBeInTheDocument();
    expect(patched()).toHaveLength(0);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("blocks invalid edits before calling the API", async () => {
    routes();
    renderEdit();
    const user = await openForm();
    await user.clear(screen.getByLabelText("Instructions"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Tell the agent what it should do.")).toBeInTheDocument();
    expect(posted()).toHaveLength(0);
  });

  it("shows members an explanation instead of the editor", () => {
    routes();
    renderEdit("member");
    expect(screen.getByText("You can view agents but not change them")).toBeInTheDocument();
    expect(screen.queryByLabelText("Instructions")).not.toBeInTheDocument();
  });

  it("shows a not-found page for a missing agent", async () => {
    routeApi({
      "GET /tools": CATALOG,
      [`GET ${AGENT}`]: apiError(404, "agent_not_found", "Agent not found."),
    });
    renderEdit();
    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
  });
});
