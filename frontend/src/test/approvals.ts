import type { Approval } from "@/lib/api/types";

/** Fixtures for the approval screens. */

export function approval(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "appr-1",
    run_id: "run-1",
    run_step_id: "step-1",
    agent_id: "agent-1",
    agent_name: "Slack helper",
    agent_version: 1,
    tool_key: "slack.send_message",
    tool_name: "Send Slack message",
    proposed_input: { channel: "C0123456789", text: "Deploy finished" },
    reasoning_summary: "The user asked me to announce that the deploy finished.",
    status: "pending",
    requested_at: "2026-11-22T09:00:00Z",
    expires_at: "2026-11-23T09:00:00Z",
    seconds_left: 86_400,
    decided_by_id: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    ...overrides,
  };
}

export function httpApproval(overrides: Partial<Approval> = {}): Approval {
  return approval({
    id: "appr-2",
    agent_name: "Order bot",
    tool_key: "http.request",
    tool_name: "HTTP request (changes data)",
    proposed_input: {
      method: "POST",
      url: "https://api.example.com/orders",
      headers: [{ name: "Accept", value: "application/json" }],
      body: '{"qty": 1}',
      content_type: "application/json",
    },
    ...overrides,
  });
}
