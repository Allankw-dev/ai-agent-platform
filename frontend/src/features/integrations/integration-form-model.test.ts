import { describe, expect, it } from "vitest";

import {
  EMPTY_FORM,
  describeSettings,
  fromIntegration,
  splitItems,
  toConfig,
} from "@/features/integrations/integration-form-model";
import type { Integration } from "@/lib/api/types";

function integration(overrides: Partial<Integration>): Integration {
  return {
    id: "i-1",
    provider: "http",
    name: "Weather",
    status: "active",
    config: {},
    has_credential: false,
    credential_set_by_id: null,
    credential_set_by_name: null,
    credential_updated_at: null,
    created_at: "2026-11-16T00:00:00Z",
    updated_at: "2026-11-16T00:00:00Z",
    ...overrides,
  };
}

describe("splitItems", () => {
  it("splits on lines, commas and spaces and drops blanks", () => {
    expect(splitItems(" a.example.com\n\nb.example.com, c.example.com  ")).toEqual([
      "a.example.com",
      "b.example.com",
      "c.example.com",
    ]);
    expect(splitItems("")).toEqual([]);
    expect(splitItems(" \n ")).toEqual([]);
  });
});

describe("toConfig", () => {
  it("builds the HTTP settings", () => {
    expect(
      toConfig({ ...EMPTY_FORM, provider: "http", hosts: "api.example.com\nb.example.com" }),
    ).toEqual({
      allowed_hosts: ["api.example.com", "b.example.com"],
      auth_header: "Authorization",
      auth_scheme: "Bearer",
    });
  });

  it("keeps an empty prefix empty and falls back to Authorization for a blank header", () => {
    expect(toConfig({ ...EMPTY_FORM, authHeader: " ", authScheme: "" })).toMatchObject({
      auth_header: "Authorization",
      auth_scheme: "",
    });
  });

  it("builds the Slack settings and never includes the secret", () => {
    const config = toConfig({
      ...EMPTY_FORM,
      provider: "slack",
      channels: "C0123456789 G0123456789",
      secret: "xoxb-very-secret",
    });
    expect(config).toEqual({ allowed_channels: ["C0123456789", "G0123456789"] });
    expect(JSON.stringify(toConfig({ ...EMPTY_FORM, secret: "xoxb-very-secret" }))).not.toContain(
      "xoxb-very-secret",
    );
  });
});

describe("fromIntegration", () => {
  it("loads the settings for editing, with no secret", () => {
    const values = fromIntegration(
      integration({
        has_credential: true,
        config: { allowed_hosts: ["a.example.com", "b.example.com"], auth_scheme: "" },
      }),
    );
    expect(values.hosts).toBe("a.example.com\nb.example.com");
    expect(values.authScheme).toBe("");
    expect(values.authHeader).toBe("Authorization");
    expect(values.secret).toBe("");
  });

  it("loads a Slack integration", () => {
    const values = fromIntegration(
      integration({ provider: "slack", config: { allowed_channels: ["C0123456789"] } }),
    );
    expect(values.provider).toBe("slack");
    expect(values.channels).toBe("C0123456789");
  });
});

describe("describeSettings", () => {
  it("says plainly when nothing is allowed", () => {
    expect(describeSettings(integration({ config: { allowed_hosts: [] } }))).toMatch(
      /No hosts allowed/,
    );
    expect(describeSettings(integration({ provider: "slack", config: {} }))).toMatch(
      /No channels allowed/,
    );
  });

  it("lists what is allowed", () => {
    expect(describeSettings(integration({ config: { allowed_hosts: ["a.example.com"] } }))).toBe(
      "Allowed hosts: a.example.com",
    );
  });
});
