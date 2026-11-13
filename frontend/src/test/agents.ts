import { OrgProvider } from "@/features/orgs/org-context";
import type {
  AgentListItem,
  AgentRead,
  OrgRole,
  Organization,
  ToolInfo,
  VersionRead,
  VersionSummary,
} from "@/lib/api/types";
import { createElement, type ReactNode } from "react";

/** Fixtures for the agent screens. */

export const orgFor = (role: OrgRole): Organization => ({
  id: "org-1",
  name: "Acme Inc",
  slug: "acme-inc",
  created_at: "2026-11-01T00:00:00Z",
  role,
});

export const inOrg = (role: OrgRole, children: ReactNode) =>
  createElement(OrgProvider, { value: orgFor(role) }, children);

export const CALCULATOR: ToolInfo = {
  key: "utility.calculate",
  name: "Calculator",
  description: "Evaluate an arithmetic expression.",
  input_schema: { type: "object" },
  is_sensitive: false,
  timeout_seconds: 5,
};

export const CLOCK: ToolInfo = {
  key: "utility.current_time",
  name: "Current time",
  description: "Get the current date and time.",
  input_schema: { type: "object" },
  is_sensitive: false,
  timeout_seconds: 5,
};

export const SENDER: ToolInfo = {
  key: "slack.send_message",
  name: "Send Slack message",
  description: "Post a message to a channel.",
  input_schema: { type: "object" },
  is_sensitive: true,
  timeout_seconds: 10,
};

export const CATALOG = [CALCULATOR, CLOCK, SENDER];

export function version(number: number, overrides: Partial<VersionRead> = {}): VersionRead {
  return {
    id: `ver-${number}`,
    version: number,
    provider: "gemini",
    model: "gemini-3-flash-preview",
    change_note: null,
    created_by_id: "user-me",
    created_at: "2026-11-10T09:00:00Z",
    system_instructions: "You help with maths.",
    objectives: null,
    model_params: { max_output_tokens: null },
    memory_config: { conversation_memory: true, max_history_messages: 20 },
    limits: {
      max_iterations: 10,
      timeout_seconds: 120,
      max_total_tokens: 50_000,
      cost_budget_usd: null,
    },
    tools: [],
    ...overrides,
  };
}

export const summary = (v: VersionRead): VersionSummary => ({
  id: v.id,
  version: v.version,
  provider: v.provider,
  model: v.model,
  change_note: v.change_note,
  created_by_id: v.created_by_id,
  created_at: v.created_at,
});

export function agent(overrides: Partial<AgentRead> = {}): AgentRead {
  return {
    id: "agent-1",
    name: "Math helper",
    description: "Answers arithmetic questions.",
    status: "active",
    created_at: "2026-11-09T09:00:00Z",
    updated_at: "2026-11-10T09:00:00Z",
    current_version: version(2),
    ...overrides,
  };
}

export const listItem = (a: AgentRead): AgentListItem => ({
  id: a.id,
  name: a.name,
  description: a.description,
  status: a.status,
  created_at: a.created_at,
  updated_at: a.updated_at,
  current_version: a.current_version ? summary(a.current_version) : null,
});

export const pageOf = <T>(items: T[], total = items.length) => ({
  items,
  total,
  limit: 20,
  offset: 0,
});
