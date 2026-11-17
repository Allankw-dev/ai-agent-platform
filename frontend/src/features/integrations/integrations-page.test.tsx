import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationsPage } from "@/features/integrations/integrations-page";
import { OrgProvider } from "@/features/orgs/org-context";
import type { Integration, OrgRole } from "@/lib/api/types";
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

const SECRET = "xoxb-1234567890-SUPER-SECRET";
const LIST = "GET /organizations/org-1/integrations";
const BASE = "/organizations/org-1/integrations";

function integration(overrides: Partial<Integration> = {}): Integration {
  return {
    id: "int-1",
    provider: "slack",
    name: "Team Slack",
    status: "active",
    config: { allowed_channels: ["C0123456789"] },
    has_credential: false,
    credential_set_by_id: null,
    credential_set_by_name: null,
    credential_updated_at: null,
    created_at: "2026-11-16T09:00:00Z",
    updated_at: "2026-11-16T09:00:00Z",
    ...overrides,
  };
}

const withSecret = (): Integration =>
  integration({
    has_credential: true,
    credential_set_by_id: "u-1",
    credential_set_by_name: "Ada Admin",
    credential_updated_at: "2026-11-16T10:00:00Z",
  });

const page = (items: Integration[]) => ({ items, total: items.length, limit: 50, offset: 0 });

function renderAs(role: OrgRole) {
  const org = { id: "org-1", name: "Acme", slug: "acme", created_at: "x", role };
  return renderWithQuery(
    <OrgProvider value={org}>
      <IntegrationsPage />
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
      screen.getByText(/Only owners, admins and developers can see integrations/),
    ).toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("lets developers see integrations but not change anything", async () => {
    routeApi({ [LIST]: page([withSecret()]) });
    renderAs("developer");
    expect(await screen.findByText("Team Slack")).toBeInTheDocument();
    expect(screen.getByText(/Only owners and admins can add or change/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/Secret saved by Ada Admin/)).toBeInTheDocument();
  });

  it.each(["owner", "admin"] as const)("lets %ss manage integrations", async (role) => {
    routeApi({ [LIST]: page([withSecret()]) });
    renderAs(role);
    await screen.findByText("Team Slack");
    expect(screen.getByRole("button", { name: "Add integration" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Replace secret for Team Slack" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Team Slack" })).toBeInTheDocument();
  });
});

describe("the list", () => {
  it("says whether a secret is saved, by whom and when, and never shows it", async () => {
    routeApi({
      [LIST]: page([
        withSecret(),
        integration({
          id: "int-2",
          provider: "http",
          name: "Weather API",
          config: { allowed_hosts: [] },
        }),
      ]),
    });
    renderAs("admin");
    await screen.findByText("Team Slack");
    expect(screen.getByText(/Secret saved by Ada Admin on/)).toBeInTheDocument();
    expect(screen.getByText("No secret saved.")).toBeInTheDocument();
    expect(screen.getByText(/Allowed channels: C0123456789/)).toBeInTheDocument();
    expect(screen.getByText(/No hosts allowed yet/)).toBeInTheDocument();
  });

  it("explains an empty list differently to managers and developers", async () => {
    routeApi({ [LIST]: page([]) });
    const { unmount } = renderAs("admin");
    expect(await screen.findByText(/No integrations yet. Add one/)).toBeInTheDocument();
    unmount();
    renderAs("developer");
    expect(await screen.findByText(/An owner or admin can add them/)).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    routeApi({ [LIST]: apiError(500, "boom", "The server had a problem.") });
    renderAs("admin");
    expect(await screen.findByText("The server had a problem.")).toBeInTheDocument();
  });
});

describe("adding an integration", () => {
  it("creates it and saves the secret in a separate write-only request", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([]),
      [`POST ${BASE}`]: integration({ id: "int-9", name: "Team Slack" }),
      [`PUT ${BASE}/int-9/credential`]: withSecret(),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add integration" }));

    await user.selectOptions(screen.getByLabelText("Type"), "slack");
    await user.type(screen.getByLabelText("Name"), "Team Slack");
    await user.type(screen.getByLabelText("Allowed channels"), "C0123456789");
    const secretBox = screen.getByLabelText("Secret (optional)");
    expect(secretBox).toHaveAttribute("type", "password");
    await user.type(secretBox, SECRET);
    await user.click(screen.getByRole("button", { name: "Add integration", hidden: false }));

    await waitFor(() => expect(callsTo("PUT", `${BASE}/int-9/credential`)).toHaveLength(1));
    const [, createOptions] = callsTo("POST", BASE)[0] as [string, { body: unknown }];
    expect(createOptions.body).toEqual({
      provider: "slack",
      name: "Team Slack",
      config: { allowed_channels: ["C0123456789"] },
    });
    // The secret travels only in the credential request, never with the settings.
    expect(JSON.stringify(createOptions.body)).not.toContain(SECRET);
    const [, putOptions] = callsTo("PUT", `${BASE}/int-9/credential`)[0] as [
      string,
      { body: unknown },
    ];
    expect(putOptions.body).toEqual({ secret: SECRET });
    await waitFor(() =>
      expect(screen.queryByLabelText("Secret (optional)")).not.toBeInTheDocument(),
    );
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("does not call the credential endpoint when no secret was typed", async () => {
    const user = userEvent.setup();
    routeApi({ [LIST]: page([]), [`POST ${BASE}`]: integration() });
    renderAs("owner");
    await user.click(await screen.findByRole("button", { name: "Add integration" }));
    await user.type(screen.getByLabelText("Name"), "Weather API");
    await user.type(screen.getByLabelText("Allowed hosts"), "api.example.com");
    await user.click(screen.getByRole("button", { name: "Add integration" }));
    await waitFor(() => expect(callsTo("POST", BASE)).toHaveLength(1));
    const [, options] = callsTo("POST", BASE)[0] as [string, { body: { config: unknown } }];
    expect(options.body.config).toEqual({
      allowed_hosts: ["api.example.com"],
      auth_header: "Authorization",
      auth_scheme: "Bearer",
    });
    expect(apiFetch.mock.calls.some(([, o]) => (o as { method?: string })?.method === "PUT")).toBe(
      false,
    );
  });

  it("asks for a name before calling the API", async () => {
    const user = userEvent.setup();
    routeApi({ [LIST]: page([]) });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add integration" }));
    await user.click(screen.getByRole("button", { name: "Add integration" }));
    expect(await screen.findByText(/at least 2 characters/)).toBeInTheDocument();
    expect(callsTo("POST", BASE)).toHaveLength(0);
  });

  it("shows the server's reason when the settings are refused", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([]),
      [`POST ${BASE}`]: apiError(
        422,
        "invalid_integration_config",
        "allowed_hosts: 'http://x.com' is not a valid host name.",
      ),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add integration" }));
    await user.type(screen.getByLabelText("Name"), "Weather API");
    await user.type(screen.getByLabelText("Allowed hosts"), "http://x.com");
    await user.click(screen.getByRole("button", { name: "Add integration" }));
    expect(await screen.findByText(/is not a valid host name/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInTheDocument(); // the form stays open
  });

  it("keeps the integration and says so when only its secret failed to save", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([]),
      [`POST ${BASE}`]: integration({ id: "int-9" }),
      [`PUT ${BASE}/int-9/credential`]: apiError(
        503,
        "credentials_not_configured",
        "Saving and using credentials needs CREDENTIAL_ENCRYPTION_KEY to be set on the server.",
      ),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add integration" }));
    await user.type(screen.getByLabelText("Name"), "Team Slack");
    await user.type(screen.getByLabelText("Secret (optional)"), SECRET);
    await user.click(screen.getByRole("button", { name: "Add integration" }));
    expect(await screen.findByText(/was added, but its secret was not saved/)).toBeInTheDocument();
    expect(screen.getByText(/CREDENTIAL_ENCRYPTION_KEY/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
  });
});

describe("secrets", () => {
  it("saves a replacement secret, then clears the box", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([withSecret()]),
      [`PUT ${BASE}/int-1/credential`]: withSecret(),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Replace secret for Team Slack" }));
    const box = screen.getByLabelText("New secret");
    expect(box).toHaveAttribute("type", "password");
    expect(box).toHaveValue("");
    await user.type(box, SECRET);
    await user.click(screen.getByRole("button", { name: "Save secret" }));

    await waitFor(() => expect(callsTo("PUT", `${BASE}/int-1/credential`)).toHaveLength(1));
    const [, options] = callsTo("PUT", `${BASE}/int-1/credential`)[0] as [
      string,
      { body: unknown },
    ];
    expect(options.body).toEqual({ secret: SECRET });
    await waitFor(() => expect(screen.queryByLabelText("New secret")).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("never leaves a rejected secret on screen", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([integration()]),
      [`PUT ${BASE}/int-1/credential`]: apiError(
        503,
        "credentials_not_configured",
        "Saving and using credentials needs CREDENTIAL_ENCRYPTION_KEY to be set on the server.",
      ),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add secret for Team Slack" }));
    await user.type(screen.getByLabelText("Secret"), SECRET);
    await user.click(screen.getByRole("button", { name: "Save secret" }));
    expect(await screen.findByText(/CREDENTIAL_ENCRYPTION_KEY/)).toBeInTheDocument();
    expect(screen.getByLabelText("Secret")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Save secret" })).toBeDisabled();
  });

  it("will not send an empty secret", async () => {
    const user = userEvent.setup();
    routeApi({ [LIST]: page([integration()]) });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add secret for Team Slack" }));
    expect(screen.getByRole("button", { name: "Save secret" })).toBeDisabled();
  });

  it("removes a secret only after confirmation", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([withSecret()]),
      [`DELETE ${BASE}/int-1/credential`]: undefined,
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Replace secret for Team Slack" }));
    await user.click(screen.getByRole("button", { name: "Remove secret" }));
    expect(callsTo("DELETE", `${BASE}/int-1/credential`)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Confirm remove secret" }));
    await waitFor(() => expect(callsTo("DELETE", `${BASE}/int-1/credential`)).toHaveLength(1));
  });

  it("offers no way to remove a secret that is not there", async () => {
    const user = userEvent.setup();
    routeApi({ [LIST]: page([integration()]) });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Add secret for Team Slack" }));
    expect(screen.queryByRole("button", { name: "Remove secret" })).not.toBeInTheDocument();
  });
});

describe("changing an integration", () => {
  it("disables and re-enables it", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([integration()]),
      [`PATCH ${BASE}/int-1`]: integration({ status: "disabled" }),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Disable Team Slack" }));
    await waitFor(() => expect(callsTo("PATCH", `${BASE}/int-1`)).toHaveLength(1));
    const [, options] = callsTo("PATCH", `${BASE}/int-1`)[0] as [string, { body: unknown }];
    expect(options.body).toEqual({ status: "disabled" });
  });

  it("offers Enable for a disabled integration", async () => {
    routeApi({ [LIST]: page([integration({ status: "disabled" })]) });
    renderAs("admin");
    expect(await screen.findByRole("button", { name: "Enable Team Slack" })).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });

  it("edits the name and settings without touching the secret", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([withSecret()]),
      [`PATCH ${BASE}/int-1`]: withSecret(),
    });
    renderAs("admin");
    await user.click(await screen.findByRole("button", { name: "Edit settings of Team Slack" }));
    expect(screen.queryByLabelText(/Secret/)).not.toBeInTheDocument();
    const channels = screen.getByLabelText("Allowed channels");
    expect(channels).toHaveValue("C0123456789");
    await user.clear(channels);
    await user.type(channels, "C0AAAAAAAAA{enter}C0BBBBBBBBB");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(callsTo("PATCH", `${BASE}/int-1`)).toHaveLength(1));
    const [, options] = callsTo("PATCH", `${BASE}/int-1`)[0] as [string, { body: unknown }];
    expect(options.body).toEqual({
      name: "Team Slack",
      config: { allowed_channels: ["C0AAAAAAAAA", "C0BBBBBBBBB"] },
    });
  });

  it("deletes only after confirmation", async () => {
    const user = userEvent.setup();
    routeApi({
      [LIST]: page([withSecret()]),
      [`DELETE ${BASE}/int-1`]: undefined,
    });
    renderAs("owner");
    await user.click(await screen.findByRole("button", { name: "Delete Team Slack" }));
    expect(screen.getByText(/Delete “Team Slack” and its secret/)).toBeInTheDocument();
    expect(callsTo("DELETE", `${BASE}/int-1`)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(callsTo("DELETE", `${BASE}/int-1`)).toHaveLength(1));
  });

  it("can back out of deleting", async () => {
    const user = userEvent.setup();
    routeApi({ [LIST]: page([integration()]) });
    renderAs("owner");
    await user.click(await screen.findByRole("button", { name: "Delete Team Slack" }));
    const card = screen.getByText(/Delete “Team Slack”/).closest("li") as HTMLElement;
    await user.click(within(card).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/Delete “Team Slack”/)).not.toBeInTheDocument();
    expect(callsTo("DELETE", `${BASE}/int-1`)).toHaveLength(0);
  });
});
