import type {
  AgentConfigInput,
  AgentRead,
  IntegrationProvider,
  MemoryConfig,
  ToolAssignmentInput,
} from "@/lib/api/types";

/**
 * The agent form's state and rules, kept free of React so they can be tested on their own.
 * Validation mirrors the API's rules to give quick feedback; the API remains the source of truth.
 */

export const DEFAULT_MODEL = "gemini-3-flash-preview";

/** Offered as suggestions only: model names change, so any valid name can be typed. */
export const MODEL_SUGGESTIONS = [
  "gemini-3-flash-preview",
  "gemini-flash-lite-latest",
  "gemini-3.1-flash-lite-preview",
  "gemini-flash-latest",
];

/** The platform's default ceilings (the API enforces the real ones and explains any refusal). */
export const LIMITS = {
  maxIterations: { min: 1, max: 25 },
  maxToolCalls: { min: 1, max: 100 },
  timeoutSeconds: { min: 5, max: 300 },
  maxTotalTokens: { min: 1_000, max: 500_000 },
  costBudgetUsd: { max: 5 },
  maxOutputTokens: { min: 1, max: 65_536 },
} as const;

const DEFAULT_MEMORY: MemoryConfig = { conversation_memory: false, max_history_messages: 20 };
const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$/;

export type ToolSelection = {
  toolKey: string;
  requiresApproval: boolean;
  /**
   * The tool's settings. For a tool that needs an integration this is `{ integration_id }`, chosen
   * in the form; for other tools it is carried through untouched.
   */
  config: Record<string, unknown>;
  /** The integration type the tool needs (undefined or null when it needs none). */
  provider?: IntegrationProvider | null;
};

/**
 * A tool that needs an integration and has none chosen gets the only fitting one (active and of
 * the right type), if there is exactly one. With none or several, the person chooses.
 */
export function autoChooseIntegrations(
  tools: ToolSelection[],
  integrations: { id: string; provider: IntegrationProvider; status: string }[] | undefined,
): ToolSelection[] {
  if (!integrations) return tools;
  let changed = false;
  const next = tools.map((selection) => {
    if (!selection.provider || integrationIdOf(selection)) return selection;
    const fitting = integrations.filter(
      (item) => item.provider === selection.provider && item.status === "active",
    );
    const only = fitting.length === 1 ? fitting[0] : undefined;
    if (!only) return selection;
    changed = true;
    return { ...selection, config: { ...selection.config, integration_id: only.id } };
  });
  return changed ? next : tools;
}

/** The integration chosen for a tool, or "" when none is chosen yet. */
export function integrationIdOf(selection: ToolSelection): string {
  const id = selection.config.integration_id;
  return typeof id === "string" ? id : "";
}

export type AgentFormValues = {
  name: string;
  description: string;
  model: string;
  instructions: string;
  objectives: string;
  tools: ToolSelection[];
  maxIterations: string;
  maxToolCalls: string;
  timeoutSeconds: string;
  maxTotalTokens: string;
  costBudget: string;
  maxOutputTokens: string;
  /** Carried through untouched: conversation memory is not applied to runs yet. */
  memory: MemoryConfig;
  changeNote: string;
};

export type AgentFormField =
  | "name"
  | "description"
  | "model"
  | "instructions"
  | "objectives"
  | "maxIterations"
  | "maxToolCalls"
  | "timeoutSeconds"
  | "maxTotalTokens"
  | "costBudget"
  | "maxOutputTokens"
  | "tools"
  | "changeNote";

export type AgentFormErrors = Partial<Record<AgentFormField, string>>;

export function emptyFormValues(): AgentFormValues {
  return {
    name: "",
    description: "",
    model: DEFAULT_MODEL,
    instructions: "",
    objectives: "",
    tools: [],
    maxIterations: "10",
    maxToolCalls: "20",
    timeoutSeconds: "120",
    maxTotalTokens: "50000",
    costBudget: "",
    maxOutputTokens: "",
    memory: { ...DEFAULT_MEMORY },
    changeNote: "",
  };
}

/** Form values for editing: the agent's details plus its current version's settings. */
export function valuesFromAgent(agent: AgentRead): AgentFormValues {
  const base = emptyFormValues();
  const version = agent.current_version;
  const values: AgentFormValues = {
    ...base,
    name: agent.name,
    description: agent.description ?? "",
  };
  if (!version) return values;
  const limits = version.limits;
  return {
    ...values,
    model: version.model,
    instructions: version.system_instructions,
    objectives: version.objectives ?? "",
    tools: version.tools.map((tool) => ({
      toolKey: tool.tool_key,
      requiresApproval: tool.requires_approval,
      config: tool.config,
      provider: tool.provider,
    })),
    maxIterations: String(limits.max_iterations ?? base.maxIterations),
    maxToolCalls: String(limits.max_tool_calls ?? base.maxToolCalls),
    timeoutSeconds: String(limits.timeout_seconds ?? base.timeoutSeconds),
    maxTotalTokens: String(limits.max_total_tokens ?? base.maxTotalTokens),
    costBudget: limits.cost_budget_usd == null ? "" : String(limits.cost_budget_usd),
    maxOutputTokens:
      version.model_params.max_output_tokens == null
        ? ""
        : String(version.model_params.max_output_tokens),
    memory: {
      conversation_memory: version.memory_config.conversation_memory ?? false,
      max_history_messages: version.memory_config.max_history_messages ?? 20,
    },
  };
}

const WHOLE_NUMBER = /^\d+$/;
const DECIMAL = /^\d+(\.\d+)?$/;

function checkWholeNumber(
  value: string,
  range: { min: number; max: number },
  label: string,
): string | undefined {
  const text = value.trim();
  if (!WHOLE_NUMBER.test(text)) return `Enter a whole number for ${label}.`;
  const number = Number(text);
  if (number < range.min || number > range.max) {
    return `Use a number from ${range.min.toLocaleString("en")} to ${range.max.toLocaleString("en")}.`;
  }
  return undefined;
}

export function validateAgentForm(
  values: AgentFormValues,
  mode: "create" | "edit",
): AgentFormErrors {
  const errors: AgentFormErrors = {};

  const name = values.name.trim();
  if (name.length < 2) errors.name = "Use at least 2 characters.";
  else if (name.length > 200) errors.name = "Use at most 200 characters.";

  if (values.description.trim().length > 2_000) {
    errors.description = "Use at most 2,000 characters.";
  }

  const model = values.model.trim();
  if (!model) errors.model = "Enter a model name.";
  else if (!MODEL_PATTERN.test(model)) {
    errors.model = "Use letters, numbers and . _ : / - only, starting with a letter or number.";
  }

  if (!values.instructions.trim()) errors.instructions = "Tell the agent what it should do.";
  else if (values.instructions.length > 20_000)
    errors.instructions = "Use at most 20,000 characters.";

  if (values.objectives.trim().length > 4_000) errors.objectives = "Use at most 4,000 characters.";

  const iterations = checkWholeNumber(values.maxIterations, LIMITS.maxIterations, "model calls");
  if (iterations) errors.maxIterations = iterations;
  const toolCalls = checkWholeNumber(values.maxToolCalls, LIMITS.maxToolCalls, "tool calls");
  if (toolCalls) errors.maxToolCalls = toolCalls;
  const timeout = checkWholeNumber(values.timeoutSeconds, LIMITS.timeoutSeconds, "seconds");
  if (timeout) errors.timeoutSeconds = timeout;
  const tokens = checkWholeNumber(values.maxTotalTokens, LIMITS.maxTotalTokens, "tokens");
  if (tokens) errors.maxTotalTokens = tokens;

  const budget = values.costBudget.trim();
  if (budget) {
    if (!DECIMAL.test(budget) || Number(budget) <= 0) {
      errors.costBudget = "Enter an amount in US dollars greater than 0, or leave it empty.";
    } else if (Number(budget) > LIMITS.costBudgetUsd.max) {
      errors.costBudget = `The platform allows at most $${LIMITS.costBudgetUsd.max} per run.`;
    }
  }

  if (values.maxOutputTokens.trim()) {
    const output = checkWholeNumber(values.maxOutputTokens, LIMITS.maxOutputTokens, "tokens");
    if (output) errors.maxOutputTokens = output;
  }

  if (values.tools.some((tool) => tool.provider && !integrationIdOf(tool))) {
    errors.tools = "Choose an integration for each tool that needs one.";
  }

  if (mode === "edit" && values.changeNote.trim().length > 500) {
    errors.changeNote = "Use at most 500 characters.";
  }
  return errors;
}

/** The API's shape for these values. Call only after validation passes. */
export function toAgentConfig(values: AgentFormValues): AgentConfigInput {
  const budget = values.costBudget.trim();
  const output = values.maxOutputTokens.trim();
  const tools: ToolAssignmentInput[] = values.tools.map((tool) => ({
    tool_key: tool.toolKey,
    requires_approval: tool.requiresApproval,
    config: tool.config,
  }));
  return {
    provider: "gemini",
    model: values.model.trim(),
    system_instructions: values.instructions,
    objectives: values.objectives.trim() ? values.objectives : null,
    model_params: { max_output_tokens: output ? Number(output) : null },
    memory_config: values.memory,
    limits: {
      max_iterations: Number(values.maxIterations.trim()),
      max_tool_calls: Number(values.maxToolCalls.trim()),
      timeout_seconds: Number(values.timeoutSeconds.trim()),
      max_total_tokens: Number(values.maxTotalTokens.trim()),
      cost_budget_usd: budget ? Number(budget) : null,
    },
    tools,
  };
}

/** Do two configurations behave identically? Tool order does not matter. */
export function sameConfig(a: AgentConfigInput, b: AgentConfigInput): boolean {
  const normalize = (config: AgentConfigInput) =>
    JSON.stringify({
      ...config,
      tools: [...config.tools].sort((x, y) => x.tool_key.localeCompare(y.tool_key)),
    });
  return normalize(a) === normalize(b);
}
