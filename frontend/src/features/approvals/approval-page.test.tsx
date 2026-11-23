import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalPage } from "@/features/approvals/approval-page";
import { APPROVAL_POLL_MS } from "@/lib/api/queries";
import type { Approval, OrgRole } from "@/lib/api/types";
import { inOrg } from "@/test/agents";
import { approval, httpApproval } from "@/test/approvals";
import { apiError, apiFetch, callsTo, routeApi } from "@/test/api-mock";
import { resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation } from "@/test/next-navigation";
import { renderWithQuery } from "@/test/render";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);
vi.mock("@/lib/api-client", async (importOriginal) =>
  (await import("@/test/api-mock")).apiClientFactory(importOriginal),
);

const ONE = "/organizations/org-1/approvals/appr-1";
const render = (role: OrgRole = "owner") => renderWithQuery(inOrg(role, <ApprovalPage />));

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
  nav.params = { orgId: "org-1", approvalId: "appr-1" };
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-22T10:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

/** A server whose approval changes when someone decides, as the real one does. */
function serve(initial: Approval = approval()) {
  let current = initial;
  const decided = (status: "approved" | "rejected", body?: { note?: string }) => {
    current = {
      ...current,
      status,
      decided_by_name: "Ada Admin",
      decided_at: "2026-11-22T10:00:00Z",
      decision_note: body?.note ?? null,
      seconds_left: null,
    };
    return current;
  };
  routeApi({
    [`GET ${ONE}`]: () => current,
    [`POST ${ONE}/approve`]: (call: { body?: { note?: string } }) => decided("approved", call.body),
    [`POST ${ONE}/reject`]: (call: { body?: { note?: string } }) => decided("rejected", call.body),
  });
  return { set: (next: Approval) => (current = next), get: () => current };
}

describe("who can open it", () => {
  it("shows a member nothing and asks the server for nothing", () => {
    render("member");
    expect(
      screen.getByText(/Only owners, admins and developers can see approvals/),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("shows a developer the request but no way to decide", async () => {
    serve();
    render("developer");
    await screen.findByText("What will run if you approve");
    expect(screen.getByText(/Only owners and admins can approve or reject/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("says when the approval does not exist", async () => {
    routeApi({ [`GET ${ONE}`]: apiError(404, "approval_not_found", "Approval not found.") });
    render();
    expect(await screen.findByText("Approval not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All approvals/ })).toHaveAttribute(
      "href",
      "/orgs/org-1/approvals",
    );
  });

  it("shows another kind of load error", async () => {
    routeApi({ [`GET ${ONE}`]: apiError(500, "boom", "The server had a problem.") });
    render();
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});

describe("a waiting request", () => {
  it("shows exactly what will run, who asked, and when it expires", async () => {
    serve();
    render();
    expect(await screen.findByRole("heading", { name: "Send Slack message" })).toBeInTheDocument();
    expect(screen.getByText("Waiting for a decision", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Slack helper" })).toHaveAttribute(
      "href",
      "/orgs/org-1/agents/agent-1",
    );
    expect(screen.getByText(/Expires in 23 h/)).toBeInTheDocument();
    expect(screen.getByText("What will run if you approve")).toBeInTheDocument();
    expect(screen.getByText("C0123456789", { selector: "code" })).toBeInTheDocument();
    expect(screen.getByText("Exact data")).toBeInTheDocument();
  });

  it("shows the agent's reason, labelled as unchecked", async () => {
    serve();
    render();
    await screen.findByText("Why the agent asked");
    expect(screen.getByText(/announce that the deploy finished/)).toBeInTheDocument();
    expect(screen.getByText(/It is not checked, so judge the action above/)).toBeInTheDocument();
  });

  it("leaves the reason out when the agent gave none", async () => {
    serve(approval({ reasoning_summary: null }));
    render();
    await screen.findByText("What will run if you approve");
    expect(screen.queryByText("Why the agent asked")).toBeNull();
  });

  it("previews an HTTP write", async () => {
    nav.params = { orgId: "org-1", approvalId: "appr-1" };
    serve(httpApproval({ id: "appr-1" }));
    render();
    expect(await screen.findByText("https://api.example.com/orders")).toBeInTheDocument();
    expect(screen.getByText("POST")).toBeInTheDocument();
  });
});

describe("approving", () => {
  it("asks for confirmation first, and sends nothing until it is given", async () => {
    serve();
    render();
    await user().click(await screen.findByRole("button", { name: "Approve" }));
    expect(screen.getByText("Approve and run this action now?")).toBeInTheDocument();
    expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(0);

    await user().click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(0);
  });

  it("approves once confirmed, and then shows the outcome", async () => {
    serve();
    render();
    await user().click(await screen.findByRole("button", { name: "Approve" }));
    await user().click(screen.getByRole("button", { name: "Yes, approve and run it" }));

    await waitFor(() => expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(1));
    expect(await screen.findByText(/Approved by Ada Admin/)).toBeInTheDocument();
    expect(screen.getByText(/The action ran once, as shown above/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/orgs/org-1/runs/run-1",
    );
  });

  it("sends the note with the decision", async () => {
    serve();
    render();
    await user().type(await screen.findByLabelText("Note (optional)"), "Checked with the team");
    await user().click(screen.getByRole("button", { name: "Approve" }));
    await user().click(screen.getByRole("button", { name: "Yes, approve and run it" }));
    await waitFor(() => expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(1));
    const [, options] = callsTo("POST", `${ONE}/approve`)[0] as [string, { body: unknown }];
    expect(options.body).toEqual({ note: "Checked with the team" });
    expect(await screen.findByText("Note: Checked with the team")).toBeInTheDocument();
  });

  it("sends no body at all when there is no note", async () => {
    serve();
    render();
    await user().click(await screen.findByRole("button", { name: "Approve" }));
    await user().click(screen.getByRole("button", { name: "Yes, approve and run it" }));
    await waitFor(() => expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(1));
    const [, options] = callsTo("POST", `${ONE}/approve`)[0] as [string, { body: unknown }];
    expect(options.body).toBeUndefined();
  });

  it("counts the note's characters and stops at the limit", async () => {
    serve();
    render();
    const box = await screen.findByLabelText("Note (optional)");
    expect(box).toHaveAttribute("maxlength", "500");
    await user().type(box, "abc");
    expect(screen.getByText("3 of 500 characters")).toBeInTheDocument();
  });

  it("cannot be double clicked into two requests", async () => {
    let release: (value: unknown) => void = () => undefined;
    const gate = new Promise((resolve) => (release = resolve));
    routeApi({
      [`GET ${ONE}`]: approval(),
      [`POST ${ONE}/approve`]: () => gate,
    });
    render();
    await user().click(await screen.findByRole("button", { name: "Approve" }));
    const confirm = screen.getByRole("button", { name: "Yes, approve and run it" });
    await user().click(confirm);
    await waitFor(() => expect(confirm).toBeDisabled());
    await user().click(confirm);
    await user().dblClick(confirm);
    expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(1);
    release(approval({ status: "approved", decided_by_name: "Ada Admin" }));
  });
});

describe("rejecting", () => {
  it("rejects in one click with the note, and shows the outcome", async () => {
    serve();
    render();
    await user().type(await screen.findByLabelText("Note (optional)"), "Use a spreadsheet");
    await user().click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(callsTo("POST", `${ONE}/reject`)).toHaveLength(1));
    const [, options] = callsTo("POST", `${ONE}/reject`)[0] as [string, { body: unknown }];
    expect(options.body).toEqual({ note: "Use a spreadsheet" });
    expect(await screen.findByText(/Rejected by Ada Admin/)).toBeInTheDocument();
    expect(
      screen.getByText(/The agent was told a person said no, and nothing ran/),
    ).toBeInTheDocument();
    expect(screen.getByText("Note: Use a spreadsheet")).toBeInTheDocument();
  });
});

describe("when the server says no", () => {
  it("shows the reason for a decision that was too late, and what really happened", async () => {
    let current = approval();
    routeApi({
      [`GET ${ONE}`]: () => current,
      // Someone else approved first: the server refuses ours and now reports their decision.
      [`POST ${ONE}/reject`]: () => {
        current = approval({
          status: "approved",
          decided_by_name: "Sam Owner",
          decided_at: "2026-11-22T10:00:00Z",
        });
        return apiError(
          409,
          "approval_already_decided",
          "This approval was already approved by Sam Owner.",
        );
      },
    });
    render();
    await user().click(await screen.findByRole("button", { name: "Reject" }));
    expect(
      await screen.findByText("This approval was already approved by Sam Owner."),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Approved by Sam Owner/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("offers to try again when the decision was saved but the run could not be handed on", async () => {
    let handOvers = 0;
    let current = approval();
    routeApi({
      [`GET ${ONE}`]: () => current,
      [`POST ${ONE}/approve`]: () => {
        handOvers += 1;
        current = {
          ...current,
          status: "approved",
          decided_by_name: "Ada Admin",
          decided_at: "2026-11-22T10:00:00Z",
        };
        if (handOvers === 1) {
          return apiError(
            503,
            "queue_unavailable",
            "The decision was saved, but the run could not be continued right now. Press the button again to retry.",
          );
        }
        return current;
      },
    });
    render();
    await user().click(await screen.findByRole("button", { name: "Approve" }));
    await user().click(screen.getByRole("button", { name: "Yes, approve and run it" }));

    expect(await screen.findByText(/Press the button again to retry/)).toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Try again" });
    await user().click(retry);
    await waitFor(() => expect(callsTo("POST", `${ONE}/approve`)).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Try again" })).toBeNull());
  });
});

describe("a decided request", () => {
  it.each([
    [
      "approved",
      { decided_by_name: "Ada Admin", decided_at: "2026-11-22T10:00:00Z", decision_note: "Fine" },
      /Approved by Ada Admin.*The action ran once/,
    ],
    [
      "rejected",
      { decided_by_name: "Ada Admin", decided_at: "2026-11-22T10:00:00Z", decision_note: null },
      /Rejected by Ada Admin.*nothing ran/,
    ],
    ["expired", {}, /Nobody decided in time/],
    ["cancelled", {}, /The run ended before anyone decided/],
  ] as const)("explains a %s request", async (status, extra, message) => {
    serve(approval({ status, ...extra }));
    render();
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByText("What was proposed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open the run" })).toBeInTheDocument();
  });

  it("shows a decided request's note", async () => {
    serve(
      approval({
        status: "approved",
        decided_by_name: "Ada Admin",
        decided_at: "2026-11-22T10:00:00Z",
        decision_note: "Fine by me",
      }),
    );
    render();
    expect(await screen.findByText("Note: Fine by me")).toBeInTheDocument();
  });
});

describe("keeping up with changes", () => {
  it("re-checks a waiting request, so an expiry or someone else's decision shows up", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const state = serve();
    render();
    await screen.findByText("What will run if you approve");
    const before = callsTo("GET", ONE).length;

    state.set(approval({ status: "expired" }));
    await vi.advanceTimersByTimeAsync(APPROVAL_POLL_MS + 200);

    expect(callsTo("GET", ONE).length).toBeGreaterThan(before);
    expect(await screen.findByText(/Nobody decided in time/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("stops re-checking once it is decided", async () => {
    vi.useRealTimers();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    serve(approval({ status: "approved", decided_by_name: "Ada Admin" }));
    render();
    await screen.findByText(/Approved by Ada Admin/);
    const count = callsTo("GET", ONE).length;
    await vi.advanceTimersByTimeAsync(APPROVAL_POLL_MS * 3);
    expect(callsTo("GET", ONE)).toHaveLength(count);
  });
});
