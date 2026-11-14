import type { RunDetail, RunRead, RunStepRead } from "@/lib/api/types";

/** Fixtures for the run screens. */

export function run(overrides: Partial<RunRead> = {}): RunRead {
  return {
    id: "run-1",
    agent_id: "agent-1",
    agent_name: "Business helper",
    agent_version_id: "ver-2",
    agent_version: 2,
    status: "succeeded",
    trigger: "manual",
    input: { message: "What is 16% VAT on KES 12,500?" },
    output: { text: "VAT is KES 2,000, so the total is KES 14,500.", iterations: 3 },
    error: null,
    input_tokens: 700,
    output_tokens: 150,
    cost_usd: 0,
    created_at: "2026-11-13T09:00:00Z",
    started_at: "2026-11-13T09:00:01Z",
    finished_at: "2026-11-13T09:00:04Z",
    ...overrides,
  };
}

export function step(sequence: number, overrides: Partial<RunStepRead> = {}): RunStepRead {
  return {
    id: `step-${sequence}`,
    sequence,
    step_type: "llm_call",
    status: "succeeded",
    name: "gemini-3-flash-preview",
    tool_key: null,
    input: { model: "gemini-3-flash-preview", messages: 1 },
    output: { text: "", tool_calls: [], finish: "stop" },
    error: null,
    input_tokens: 0,
    output_tokens: 0,
    started_at: "2026-11-13T09:00:01Z",
    finished_at: "2026-11-13T09:00:02Z",
    ...overrides,
  };
}

/** A typical successful run: the model asks for the calculator, then answers. */
export const STEPS: RunStepRead[] = [
  step(0, {
    input_tokens: 300,
    output_tokens: 40,
    output: {
      text: "",
      tool_calls: [{ id: "call_0", name: "utility_calculate" }],
      finish: "tool_calls",
    },
  }),
  step(1, {
    step_type: "tool_call",
    name: "utility.calculate",
    tool_key: "utility.calculate",
    input: { expression: "12500 * 0.16" },
    output: { expression: "12500 * 0.16", result: 2000 },
  }),
  step(2, {
    input_tokens: 400,
    output_tokens: 110,
    output: { text: "VAT is KES 2,000.", tool_calls: [], finish: "stop" },
  }),
];

export const runDetail = (overrides: Partial<RunDetail> = {}): RunDetail => ({
  ...run(),
  steps: STEPS,
  ...overrides,
});
