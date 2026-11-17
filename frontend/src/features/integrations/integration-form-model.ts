import type { Integration, IntegrationProvider } from "@/lib/api/types";

/** The integrations an organization can add today. Others exist in the API for later phases. */
export const CREATABLE_PROVIDERS = ["http", "slack"] as const;
export type CreatableProvider = (typeof CREATABLE_PROVIDERS)[number];

export const PROVIDER_LABELS: Record<IntegrationProvider, string> = {
  http: "HTTP / API",
  slack: "Slack",
  github: "GitHub",
  gmail: "Gmail",
  google_calendar: "Google Calendar",
  webhook: "Webhook",
};

export type IntegrationFormValues = {
  provider: CreatableProvider;
  name: string;
  /** One host name per line (HTTP). */
  hosts: string;
  authHeader: string;
  authScheme: string;
  /** One Slack channel id per line (Slack). */
  channels: string;
  /** The secret to save. Only used when adding an integration; never filled in from the server. */
  secret: string;
};

export const EMPTY_FORM: IntegrationFormValues = {
  provider: "http",
  name: "",
  hosts: "",
  authHeader: "Authorization",
  authScheme: "Bearer",
  channels: "",
  secret: "",
};

/** Lines (or comma- or space-separated items) typed into a textarea, trimmed, blanks dropped. */
export function splitItems(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** The non-secret settings to send, for the chosen provider. The server validates them again. */
export function toConfig(values: IntegrationFormValues): Record<string, unknown> {
  if (values.provider === "slack") return { allowed_channels: splitItems(values.channels) };
  return {
    allowed_hosts: splitItems(values.hosts),
    auth_header: values.authHeader.trim() || "Authorization",
    auth_scheme: values.authScheme.trim(),
  };
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

/** Form values for editing an existing integration. The secret is never loaded: it can't be. */
export function fromIntegration(integration: Integration): IntegrationFormValues {
  const config = integration.config;
  const provider: CreatableProvider = integration.provider === "slack" ? "slack" : "http";
  return {
    ...EMPTY_FORM,
    provider,
    name: integration.name,
    hosts: strings(config.allowed_hosts).join("\n"),
    authHeader: typeof config.auth_header === "string" ? config.auth_header : "Authorization",
    authScheme: typeof config.auth_scheme === "string" ? config.auth_scheme : "Bearer",
    channels: strings(config.allowed_channels).join("\n"),
  };
}

/** A one-line description of what the integration allows, for the list. */
export function describeSettings(integration: Integration): string {
  if (integration.provider === "slack") {
    const channels = strings(integration.config.allowed_channels);
    return channels.length
      ? `Allowed channels: ${channels.join(", ")}`
      : "No channels allowed yet, so agents cannot post anywhere.";
  }
  if (integration.provider === "http") {
    const hosts = strings(integration.config.allowed_hosts);
    return hosts.length
      ? `Allowed hosts: ${hosts.join(", ")}`
      : "No hosts allowed yet, so agents cannot call anything.";
  }
  return "Not available yet.";
}
