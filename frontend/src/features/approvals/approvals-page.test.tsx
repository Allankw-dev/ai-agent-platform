import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalsPage } from "@/features/approvals/approvals-page";
import type { Approval, OrgRole } from "@/lib/api/types";
import { inOrg, pageOf } from "@/test/agents";
import { approval, httpApproval } from "@/test/approvals";
import { apiError, apiFetch, routeApi } from "@/test/api-mock";
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

const LIST = "GET /organizations/org-1/approvals";
const render = (role: OrgRole = "owner") => renderWithQuery(inOrg(role, <ApprovalsPage />));

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-22T10:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

/** A server that filters by the status the screen asks for. */
function serve(all: Approval[]) {
  routeApi({
    [LIST]: (call: { query?: Record<string, unknown> }) => {
      const status = call.query?.status;
      const items = status ? all.filter((a) => a.status === status) : all;
      return pageOf(items);
    },
  });
}

describe("who can see the inbox", () => {
  it("tells members they have no access, and asks the server for nothing", () => {
    render("member");
    expect(
      screen.getByText(/Only owners, admins and developers can see approvals/),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it.each(["owner", "admin"] as const)("lets an %s see and decide", async (role) => {
    serve([approval()]);
    render(role);
    await screen.findByText("Send Slack message");
    expect(screen.queryByText(/Only owners and admins can approve or reject/)).toBeNull();
  });

  it("tells a developer they can look but not decide", async () => {
    serve([approval()]);
    render("developer");
    await screen.findByText("Send Slack message");
    expect(screen.getByText(/Only owners and admins can approve or reject/)).toBeInTheDocument();
  });
});

describe("the list", () => {
  it("opens on what is waiting, newest first as the server sends it", async () => {
    serve([approval(), httpApproval({ id: "appr-2" })]);
    render();
    await screen.findByText("Send Slack message");
    expect(apiFetch).toHaveBeenCalledWith(
      "/organizations/org-1/approvals",
      expect.objectContaining({ query: { limit: 20, status: "pending" } }),
    );
    expect(screen.getByLabelText("Filter by status")).toHaveValue("pending");
  });

  it("says what each request is, who asked, and how long is left", async () => {
    serve([approval()]);
    render();
    const link = await screen.findByRole("link", { name: "Send Slack message" });
    expect(link).toHaveAttribute("href", "/orgs/org-1/approvals/appr-1");
    expect(screen.getByText("Slack helper · v1")).toBeInTheDocument();
    expect(screen.getByText("To C0123456789: Deploy finished")).toBeInTheDocument();
    expect(screen.getByText("Waiting for a decision", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Expires in 23 h")).toBeInTheDocument();
  });

  it("summarizes an HTTP write by its method and address", async () => {
    serve([httpApproval()]);
    render();
    expect(await screen.findByText("POST https://api.example.com/orders")).toBeInTheDocument();
  });

  it("falls back to the tool's key when it has no friendly name", async () => {
    serve([approval({ tool_name: null, tool_key: "slack.send_message" })]);
    render();
    expect(await screen.findByRole("link", { name: "slack.send_message" })).toBeInTheDocument();
  });

  it("shows an overdue request as expired text, not a negative time", async () => {
    serve([approval({ expires_at: "2026-11-22T09:59:00Z" })]);
    render();
    expect(await screen.findByText("Expired", { selector: "span" })).toBeInTheDocument();
  });

  it("shows who decided on a decided one", async () => {
    const decided = approval({ status: "approved", decided_by_name: "Ada Admin" });
    serve([decided]);
    render();
    await userEvent
      .setup({ advanceTimers: vi.advanceTimersByTime })
      .selectOptions(screen.getByLabelText("Filter by status"), "approved");
    expect(await screen.findByText("Approved by Ada Admin")).toBeInTheDocument();
  });
});

describe("filtering", () => {
  it("asks the server for the chosen status", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    serve([approval(), approval({ id: "appr-3", status: "rejected", decided_by_name: "Ada" })]);
    render();
    await screen.findByText("Send Slack message");

    await user.selectOptions(screen.getByLabelText("Filter by status"), "rejected");
    await waitFor(() =>
      expect(apiFetch).toHaveBeenLastCalledWith(
        "/organizations/org-1/approvals",
        expect.objectContaining({ query: { limit: 20, status: "rejected" } }),
      ),
    );
    expect(await screen.findByText("Rejected by Ada")).toBeInTheDocument();
  });

  it("asks for everything, with no status, when All is chosen", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    serve([approval()]);
    render();
    await screen.findByText("Send Slack message");
    await user.selectOptions(screen.getByLabelText("Filter by status"), "All");
    await waitFor(() =>
      expect(apiFetch).toHaveBeenLastCalledWith(
        "/organizations/org-1/approvals",
        expect.objectContaining({ query: { limit: 20, status: undefined } }),
      ),
    );
  });
});

describe("empty and failing", () => {
  it("explains an empty waiting list", async () => {
    serve([]);
    render();
    expect(await screen.findByText("Nothing is waiting for a decision")).toBeInTheDocument();
    expect(
      screen.getByText(/When an agent wants to do something that needs approval/),
    ).toBeInTheDocument();
  });

  it("explains an empty list for another status", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    serve([]);
    render();
    await screen.findByText("Nothing is waiting for a decision");
    await user.selectOptions(screen.getByLabelText("Filter by status"), "expired");
    expect(await screen.findByText("No approvals here")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    routeApi({ [LIST]: apiError(500, "boom", "The server had a problem.") });
    render();
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });

  it("shows more when there are more than one page", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    routeApi({
      [LIST]: (call: { query?: Record<string, unknown> }) => {
        const limit = Number(call.query?.limit);
        const items = Array.from({ length: Math.min(limit, 30) }, (_, n) =>
          approval({ id: `appr-${n}` }),
        );
        return { items, total: 30, limit, offset: 0 };
      },
    });
    render();
    await screen.findAllByRole("link", { name: "Send Slack message" });
    expect(screen.getAllByRole("link", { name: "Send Slack message" })).toHaveLength(20);
    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() =>
      expect(screen.getAllByRole("link", { name: "Send Slack message" })).toHaveLength(30),
    );
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("lists each approval once, inside the list", async () => {
    serve([approval(), httpApproval()]);
    render();
    const list = await screen.findByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  });
});
