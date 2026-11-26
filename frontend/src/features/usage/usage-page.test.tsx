import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgProvider } from "@/features/orgs/org-context";
import { UsagePage } from "@/features/usage/usage-page";
import type { OrgLimits, OrgRole, Usage, UsageDay } from "@/lib/api/types";
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

const USAGE = "GET /organizations/org-1/usage";
const LIMITS_PATH = "/organizations/org-1/limits";

const limits = (overrides: Partial<OrgLimits> = {}): OrgLimits => ({
  max_concurrent_runs: 5,
  daily_token_quota: 500_000,
  daily_cost_quota_usd: null,
  customized: false,
  updated_at: null,
  ...overrides,
});

function days(today: Partial<UsageDay> = {}, count = 30): UsageDay[] {
  return Array.from({ length: count }, (_, i) => ({
    day: `2026-11-${String(i + 1).padStart(2, "0")}`,
    runs: 0,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: 0,
    ...(i === count - 1 ? today : {}),
  }));
}

function usage(overrides: Partial<Usage> = {}): Usage {
  return {
    limits: limits(),
    today: {
      input_tokens: 900,
      output_tokens: 300,
      cost_usd: 0.007,
      reserved_tokens: 800,
      busy_runs: 2,
      resets_at: "2026-11-26T00:00:00Z",
    },
    days: days({ runs: 3, input_tokens: 900, output_tokens: 300, cost_usd: 0.007 }),
    by_agent: [
      {
        agent_id: "a-1",
        agent_name: "Math helper",
        input_tokens: 900,
        output_tokens: 300,
        cost_usd: 0.007,
      },
    ],
    ...overrides,
  };
}

function renderAs(role: OrgRole) {
  const org = { id: "org-1", name: "Acme", slug: "acme", created_at: "x", role };
  return renderWithQuery(
    <OrgProvider value={org}>
      <UsagePage />
    </OrgProvider>,
  );
}

beforeEach(() => {
  resetNavigation();
  resetAuth();
  apiFetch.mockReset();
});

describe("who sees what", () => {
  it("shows members a notice and never calls the API", () => {
    renderAs("member");
    expect(
      screen.getByText(/Only owners, admins and developers can see usage/),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("lets developers see usage and the limits, but not change them", async () => {
    routeApi({ [USAGE]: usage({ limits: limits({ customized: true }) }) });
    renderAs("developer");
    expect(await screen.findByText(/of 500,000 tokens used/)).toHaveTextContent(
      "1,200 of 500,000 tokens used",
    );
    expect(screen.getByText(/Only owners and admins can change them/)).toBeInTheDocument();
    expect(screen.getByText("Runs at once")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save limits" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Reset to platform defaults/ }),
    ).not.toBeInTheDocument();
  });

  it.each(["owner", "admin"] as const)("lets an %s change the limits", async (role) => {
    routeApi({ [USAGE]: usage() });
    renderAs(role);
    expect(await screen.findByLabelText("Runs at once")).toHaveValue("5");
    expect(screen.getByRole("button", { name: "Save limits" })).toBeInTheDocument();
  });
});

describe("today", () => {
  it("shows tokens used against the quota, what runs in progress still hold, and the reset time", async () => {
    routeApi({ [USAGE]: usage() });
    renderAs("owner");
    expect(await screen.findByText(/of 500,000 tokens used/)).toHaveTextContent(
      "1,200 of 500,000 tokens used",
    );
    expect(screen.getByText("800 more held by runs in progress")).toBeInTheDocument();
    expect(screen.getByText(/900 in, 300 out/)).toBeInTheDocument();
    expect(screen.getByText(/resets at 12:00 AM UTC/)).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Tokens used today" });
    expect(bar).toHaveAttribute("aria-valuenow", "1200");
    expect(bar).toHaveAttribute("aria-valuemax", "500000");
  });

  it("shows runs now against the limit, and the estimated cost", async () => {
    routeApi({
      [USAGE]: usage({ limits: limits({ daily_cost_quota_usd: 2.5 }) }),
    });
    renderAs("owner");
    const runs = (await screen.findByText("Runs queued or running")).closest("div")!;
    expect(within(runs).getByText("2")).toBeInTheDocument();
    expect(runs).toHaveTextContent("2 of 5 allowed");
    const cost = screen.getByText("Estimated cost today").closest("div")!;
    expect(cost).toHaveTextContent("$0.0070 of $2.5");
  });

  it("does not claim tokens are held when none are", async () => {
    const quiet = usage();
    quiet.today.reserved_tokens = 0;
    routeApi({ [USAGE]: quiet });
    renderAs("owner");
    await screen.findByText(/tokens used/);
    expect(screen.queryByText(/held by runs in progress/)).not.toBeInTheDocument();
  });

  it("never lets the bar overflow when the quota is exceeded", async () => {
    const over = usage();
    over.today.input_tokens = 600_000;
    routeApi({ [USAGE]: over });
    renderAs("owner");
    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "500000");
  });
});

describe("history and agents", () => {
  it("summarises the period and shows one bar per day", async () => {
    routeApi({ [USAGE]: usage() });
    renderAs("owner");
    expect(await screen.findByText("Last 30 days")).toBeInTheDocument();
    expect(screen.getByText(/3 runs, 1,200 tokens, about \$0\.0070/)).toBeInTheDocument();
    const chart = screen.getByRole("list", { name: "Tokens used per day" });
    expect(within(chart).getAllByRole("listitem")).toHaveLength(30);
    expect(within(chart).getByLabelText("Nov 30: 1,200 tokens, 3 runs")).toBeInTheDocument();
  });

  it("says plainly when there is no usage yet, and has no agent table", async () => {
    routeApi({
      [USAGE]: usage({
        days: days(),
        by_agent: [],
        today: {
          input_tokens: 0,
          output_tokens: 0,
          cost_usd: 0,
          reserved_tokens: 0,
          busy_runs: 0,
          resets_at: "2026-11-26T00:00:00Z",
        },
      }),
    });
    renderAs("owner");
    expect(await screen.findByText(/No usage yet/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/of 500,000 tokens used/)).toHaveTextContent(
      "0 of 500,000 tokens used",
    );
  });

  it("lists the heaviest agents", async () => {
    routeApi({ [USAGE]: usage() });
    renderAs("owner");
    const table = await screen.findByRole("table");
    const row = within(table).getByRole("row", { name: /Math helper/ });
    expect(row).toHaveTextContent("1,200");
    expect(row).toHaveTextContent("$0.0070");
  });

  it("shows a failure to load as an error, not a blank page", async () => {
    routeApi({ [USAGE]: apiError(500, "boom", "The server had a problem.") });
    renderAs("owner");
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});

describe("changing the limits", () => {
  const PUT = `PUT ${LIMITS_PATH}`;

  it("saves new limits, in the API's shape, and confirms", async () => {
    const saved = limits({
      max_concurrent_runs: 8,
      daily_token_quota: 1_500_000,
      daily_cost_quota_usd: 3.5,
      customized: true,
    });
    let current = usage();
    routeApi({
      [USAGE]: () => current,
      [PUT]: () => {
        current = usage({ limits: saved });
        return saved;
      },
    });
    renderAs("owner");
    const user = userEvent.setup();
    const save = await screen.findByRole("button", { name: "Save limits" });
    expect(save).toBeDisabled(); // nothing changed yet

    await user.clear(screen.getByLabelText("Runs at once"));
    await user.type(screen.getByLabelText("Runs at once"), "8");
    await user.clear(screen.getByLabelText("Tokens per day"));
    await user.type(screen.getByLabelText("Tokens per day"), "1,500,000");
    await user.type(screen.getByLabelText(/Cost per day/), "3.5");
    await user.click(screen.getByRole("button", { name: "Save limits" }));

    await waitFor(() => expect(callsTo("PUT", LIMITS_PATH)).toHaveLength(1));
    const [, options] = callsTo("PUT", LIMITS_PATH)[0] as [string, { body: unknown }];
    expect(options.body).toEqual({
      max_concurrent_runs: 8,
      daily_token_quota: 1_500_000,
      daily_cost_quota_usd: 3.5,
    });
    expect(await screen.findByText(/Limits saved/)).toBeInTheDocument();
    // The usage is fetched again, so the bar and the numbers use the new quota.
    expect(await screen.findByText(/of 1,500,000 tokens used/)).toHaveTextContent(
      "1,200 of 1,500,000 tokens used",
    );
    expect(screen.getByLabelText("Runs at once")).toHaveValue("8");
  });

  it("points at every problem and sends nothing", async () => {
    routeApi({ [USAGE]: usage(), [PUT]: limits() });
    renderAs("owner");
    const user = userEvent.setup();
    await user.clear(await screen.findByLabelText("Runs at once"));
    await user.type(screen.getByLabelText("Runs at once"), "0");
    await user.clear(screen.getByLabelText("Tokens per day"));
    await user.type(screen.getByLabelText("Tokens per day"), "12");
    await user.type(screen.getByLabelText(/Cost per day/), "free");
    await user.click(screen.getByRole("button", { name: "Save limits" }));

    expect(screen.getByLabelText("Runs at once")).toHaveAccessibleDescription(
      "Use 1 to 1,000 runs.",
    );
    expect(screen.getByLabelText("Tokens per day")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(/Cost per day/)).toHaveAttribute("aria-invalid", "true");
    expect(callsTo("PUT", LIMITS_PATH)).toHaveLength(0);
  });

  it("shows the server's refusal and keeps what was typed", async () => {
    routeApi({
      [USAGE]: usage(),
      [PUT]: apiError(403, "forbidden", "You do not have permission to do that."),
    });
    renderAs("owner");
    const user = userEvent.setup();
    await user.clear(await screen.findByLabelText("Runs at once"));
    await user.type(screen.getByLabelText("Runs at once"), "9");
    await user.click(screen.getByRole("button", { name: "Save limits" }));
    expect(await screen.findByText("You do not have permission to do that.")).toBeInTheDocument();
    expect(screen.getByLabelText("Runs at once")).toHaveValue("9");
  });

  it("offers a reset only once limits are customized, and asks before doing it", async () => {
    let current = usage({ limits: limits({ customized: true, max_concurrent_runs: 2 }) });
    routeApi({
      [USAGE]: () => current,
      [`DELETE ${LIMITS_PATH}`]: () => {
        current = usage();
        return undefined;
      },
    });
    renderAs("owner");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Reset to platform defaults" }));
    expect(screen.getByText(/Go back to the platform defaults\?/)).toBeInTheDocument();
    expect(callsTo("DELETE", LIMITS_PATH)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(callsTo("DELETE", LIMITS_PATH)).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Reset to platform defaults" }));
    await user.click(screen.getByRole("button", { name: "Confirm reset" }));
    await waitFor(() => expect(callsTo("DELETE", LIMITS_PATH)).toHaveLength(1));
    await waitFor(() => expect(screen.getByLabelText("Runs at once")).toHaveValue("5"));
    expect(
      screen.queryByRole("button", { name: "Reset to platform defaults" }),
    ).not.toBeInTheDocument();
  });

  it("has no reset button while the platform defaults apply", async () => {
    routeApi({ [USAGE]: usage() });
    renderAs("owner");
    await screen.findByLabelText("Runs at once");
    expect(screen.queryByRole("button", { name: /Reset/ })).not.toBeInTheDocument();
    expect(screen.getByText(/The platform defaults\. Save to set your own/)).toBeInTheDocument();
  });
});
