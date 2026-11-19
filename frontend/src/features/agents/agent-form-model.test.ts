import { describe, expect, it } from "vitest";

import {
  DEFAULT_MODEL,
  autoChooseIntegrations,
  emptyFormValues,
  integrationIdOf,
  sameConfig,
  toAgentConfig,
  validateAgentForm,
  valuesFromAgent,
  type AgentFormValues,
} from "@/features/agents/agent-form-model";
import { agent, version } from "@/test/agents";

const valid = (overrides: Partial<AgentFormValues> = {}): AgentFormValues => ({
  ...emptyFormValues(),
  name: "Math helper",
  instructions: "You help with maths.",
  ...overrides,
});

describe("validateAgentForm", () => {
  it("accepts a minimal agent", () => {
    expect(validateAgentForm(valid(), "create")).toEqual({});
  });

  it("starts from the default model", () => {
    expect(emptyFormValues().model).toBe(DEFAULT_MODEL);
  });

  it.each([
    ["name", { name: "A" }, "name"],
    ["blank name", { name: "   " }, "name"],
    ["long name", { name: "x".repeat(201) }, "name"],
    ["no instructions", { instructions: "  \n " }, "instructions"],
    ["huge instructions", { instructions: "x".repeat(20_001) }, "instructions"],
    ["huge objectives", { objectives: "x".repeat(4_001) }, "objectives"],
    ["huge description", { description: "x".repeat(2_001) }, "description"],
    ["empty model", { model: " " }, "model"],
    ["model with spaces", { model: "gemini flash" }, "model"],
    ["model starting with a dash", { model: "-gemini" }, "model"],
    ["model with a slash path trick", { model: "../x;rm" }, "model"],
  ] as const)("rejects %s", (_label, overrides, field) => {
    expect(validateAgentForm(valid(overrides), "create")[field]).toBeTruthy();
  });

  it.each([
    ["maxIterations", "0"],
    ["maxIterations", "26"],
    ["maxIterations", "ten"],
    ["maxIterations", "1.5"],
    ["maxIterations", ""],
    ["timeoutSeconds", "4"],
    ["timeoutSeconds", "301"],
    ["maxTotalTokens", "999"],
    ["maxTotalTokens", "500001"],
    ["maxOutputTokens", "0"],
    ["maxOutputTokens", "65537"],
    ["maxOutputTokens", "lots"],
    ["costBudget", "0"],
    ["costBudget", "-1"],
    ["costBudget", "abc"],
    ["costBudget", "5.01"],
  ] as const)("rejects %s = %j", (field, value) => {
    expect(validateAgentForm(valid({ [field]: value }), "create")[field]).toBeTruthy();
  });

  it.each([
    ["maxIterations", "1"],
    ["maxIterations", "25"],
    ["timeoutSeconds", "5"],
    ["timeoutSeconds", "300"],
    ["maxTotalTokens", "1000"],
    ["maxTotalTokens", "500000"],
    ["maxOutputTokens", ""],
    ["maxOutputTokens", "65536"],
    ["costBudget", ""],
    ["costBudget", "0.5"],
    ["costBudget", "5"],
  ] as const)("accepts %s = %j", (field, value) => {
    expect(validateAgentForm(valid({ [field]: value }), "create")[field]).toBeUndefined();
  });

  it("checks the change note only when editing", () => {
    const long = valid({ changeNote: "x".repeat(501) });
    expect(validateAgentForm(long, "create").changeNote).toBeUndefined();
    expect(validateAgentForm(long, "edit").changeNote).toBeTruthy();
  });
});

describe("toAgentConfig", () => {
  it("turns text fields into the API's numbers and nulls", () => {
    const config = toAgentConfig(
      valid({
        model: " gemini-3-flash-preview ",
        objectives: "  ",
        maxIterations: " 7 ",
        costBudget: "0.25",
        maxOutputTokens: "2048",
        tools: [
          { toolKey: "utility.calculate", requiresApproval: false, config: {} },
          { toolKey: "slack.send_message", requiresApproval: true, config: { channel: "#ops" } },
        ],
      }),
    );
    expect(config).toEqual({
      provider: "gemini",
      model: "gemini-3-flash-preview",
      system_instructions: "You help with maths.",
      objectives: null,
      model_params: { max_output_tokens: 2048 },
      memory_config: { conversation_memory: false, max_history_messages: 20 },
      limits: {
        max_iterations: 7,
        timeout_seconds: 120,
        max_total_tokens: 50_000,
        cost_budget_usd: 0.25,
      },
      tools: [
        { tool_key: "utility.calculate", requires_approval: false, config: {} },
        { tool_key: "slack.send_message", requires_approval: true, config: { channel: "#ops" } },
      ],
    });
  });

  it("sends nulls for the optional limits when they are empty", () => {
    const config = toAgentConfig(valid());
    expect(config.model_params.max_output_tokens).toBeNull();
    expect(config.limits.cost_budget_usd).toBeNull();
  });
});

describe("valuesFromAgent", () => {
  it("round-trips an agent through the form without changing it", () => {
    const original = agent({
      current_version: version(3, {
        objectives: "Be brief.",
        model_params: { max_output_tokens: 1024 },
        memory_config: { conversation_memory: false, max_history_messages: 5 },
        limits: {
          max_iterations: 4,
          timeout_seconds: 60,
          max_total_tokens: 20_000,
          cost_budget_usd: 1.5,
        },
        tools: [
          {
            tool_key: "utility.calculate",
            name: "Calculator",
            description: "d",
            provider: null,
            is_sensitive: false,
            requires_approval: true,
            config: { precision: 2 },
          },
        ],
      }),
    });
    const values = valuesFromAgent(original);
    expect(values.name).toBe("Math helper");
    expect(values.costBudget).toBe("1.5");
    expect(values.memory).toEqual({ conversation_memory: false, max_history_messages: 5 });
    expect(validateAgentForm(values, "edit")).toEqual({});
    // Saving without touching anything must not look like a change.
    expect(sameConfig(toAgentConfig(values), toAgentConfig(valuesFromAgent(original)))).toBe(true);
  });

  it("fills in defaults for versions saved before a setting existed", () => {
    const old = agent({
      current_version: version(1, { limits: {}, model_params: {}, memory_config: {} }),
    });
    const values = valuesFromAgent(old);
    expect(values.maxIterations).toBe("10");
    expect(values.maxOutputTokens).toBe("");
    expect(values.memory).toEqual({ conversation_memory: false, max_history_messages: 20 });
  });

  it("copes with an agent that has no version", () => {
    const values = valuesFromAgent(agent({ current_version: null }));
    expect(values.name).toBe("Math helper");
    expect(values.model).toBe(DEFAULT_MODEL);
  });
});

describe("sameConfig", () => {
  it("ignores tool order but notices real differences", () => {
    const a = toAgentConfig(
      valid({
        tools: [
          { toolKey: "b.tool", requiresApproval: false, config: {} },
          { toolKey: "a.tool", requiresApproval: false, config: {} },
        ],
      }),
    );
    const reordered = { ...a, tools: [...a.tools].reverse() };
    expect(sameConfig(a, reordered)).toBe(true);

    const approval = { ...a, tools: a.tools.map((t) => ({ ...t, requires_approval: true })) };
    expect(sameConfig(a, approval)).toBe(false);
    expect(sameConfig(a, { ...a, model: "other-model" })).toBe(false);
    expect(sameConfig(a, { ...a, limits: { ...a.limits, max_iterations: 3 } })).toBe(false);
  });
});

describe("tools that need an integration", () => {
  const needs = (config: Record<string, unknown> = {}) => ({
    toolKey: "http.get",
    requiresApproval: false,
    config,
    provider: "http" as const,
  });

  it("is invalid until an integration is chosen", () => {
    const errors = validateAgentForm(valid({ tools: [needs()] }), "create");
    expect(errors.tools).toMatch(/Choose an integration/);
    expect(
      validateAgentForm(valid({ tools: [needs({ integration_id: "" })] }), "create").tools,
    ).toBeTruthy();
  });

  it("is valid once one is chosen, and the choice is sent to the API", () => {
    const values = valid({ tools: [needs({ integration_id: "int-1" })] });
    expect(validateAgentForm(values, "create").tools).toBeUndefined();
    expect(toAgentConfig(values).tools).toEqual([
      { tool_key: "http.get", requires_approval: false, config: { integration_id: "int-1" } },
    ]);
  });

  it("does not ask for an integration for tools that need none", () => {
    const plain = { toolKey: "utility.calculate", requiresApproval: false, config: {} };
    expect(validateAgentForm(valid({ tools: [plain] }), "create").tools).toBeUndefined();
    expect(
      validateAgentForm(valid({ tools: [{ ...plain, provider: null }] }), "create").tools,
    ).toBeUndefined();
  });

  it("reads the chosen integration back from a saved agent", () => {
    const saved = agent({
      current_version: version(2, {
        tools: [
          {
            tool_key: "http.get",
            name: "HTTP GET",
            description: "d",
            provider: "http",
            is_sensitive: false,
            requires_approval: false,
            config: { integration_id: "int-9" },
          },
        ],
      }),
    });
    const values = valuesFromAgent(saved);
    expect(values.tools[0]?.provider).toBe("http");
    expect(integrationIdOf(values.tools[0]!)).toBe("int-9");
    expect(sameConfig(toAgentConfig(values), toAgentConfig(valuesFromAgent(saved)))).toBe(true);
  });

  it("treats a missing or non-text integration id as not chosen", () => {
    expect(integrationIdOf(needs())).toBe("");
    expect(integrationIdOf(needs({ integration_id: 5 }))).toBe("");
  });
});

describe("autoChooseIntegrations", () => {
  const needs = {
    toolKey: "http.get",
    requiresApproval: false,
    config: {},
    provider: "http" as const,
  };
  const http = (id: string, status = "active") => ({ id, provider: "http" as const, status });

  it("chooses the only fitting integration", () => {
    expect(autoChooseIntegrations([needs], [http("a")])[0]?.config).toEqual({
      integration_id: "a",
    });
  });

  it("leaves the choice to the person when none or several fit", () => {
    expect(autoChooseIntegrations([needs], [])).toEqual([needs]);
    expect(autoChooseIntegrations([needs], [http("a"), http("b")])).toEqual([needs]);
  });

  it("ignores disabled integrations and other types", () => {
    const slack = { id: "s", provider: "slack" as const, status: "active" };
    expect(autoChooseIntegrations([needs], [http("a", "disabled"), slack])).toEqual([needs]);
    expect(autoChooseIntegrations([needs], [http("a", "disabled"), http("b")])[0]?.config).toEqual({
      integration_id: "b",
    });
  });

  it("never overrides a choice already made, nor touches tools that need none", () => {
    const chosen = { ...needs, config: { integration_id: "z" } };
    const plain = { toolKey: "utility.calculate", requiresApproval: false, config: {} };
    const result = autoChooseIntegrations([chosen, plain], [http("a")]);
    expect(result[0]?.config).toEqual({ integration_id: "z" });
    expect(result[1]).toBe(plain);
  });

  it("returns the same array when nothing changes, and waits for the list to load", () => {
    const tools = [needs];
    expect(autoChooseIntegrations(tools, [http("a"), http("b")])).toBe(tools);
    expect(autoChooseIntegrations(tools, undefined)).toBe(tools);
  });
});
