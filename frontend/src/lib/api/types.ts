export type OrgRole = "owner" | "admin" | "developer" | "member";

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type UserProfile = {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  is_super_admin: boolean;
  created_at: string;
};

export type Organization = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: OrgRole;
};

export type Member = {
  user_id: string;
  email: string;
  full_name: string | null;
  role: OrgRole;
  joined_at: string;
};

export type InvitationStatus = "pending" | "expired" | "accepted" | "revoked";

export type Invitation = {
  id: string;
  email: string;
  role: OrgRole;
  status: InvitationStatus;
  expires_at: string;
  created_at: string;
};

export type InvitationCreated = Invitation & { invite_url: string };

export type InvitationAccepted = {
  organization: { id: string; name: string; slug: string; created_at: string };
  role: OrgRole;
};

// ---------- agents ----------

export type AgentStatus = "draft" | "active" | "disabled" | "archived";
export type LLMProvider = "gemini" | "anthropic";

export type MemoryConfig = { conversation_memory: boolean; max_history_messages: number };

export type Limits = {
  max_iterations: number;
  timeout_seconds: number;
  max_total_tokens: number;
  cost_budget_usd: number | null;
};

/** A tool in the global catalog that an agent can be given. */
export type ToolInfo = {
  key: string;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  is_sensitive: boolean;
  timeout_seconds: number;
};

export type ToolAssignmentRead = {
  tool_key: string;
  name: string;
  description: string;
  is_sensitive: boolean;
  requires_approval: boolean;
  config: Record<string, unknown>;
};

export type VersionSummary = {
  id: string;
  version: number;
  provider: LLMProvider;
  model: string;
  change_note: string | null;
  created_by_id: string | null;
  created_at: string;
};

export type VersionRead = VersionSummary & {
  system_instructions: string;
  objectives: string | null;
  // Stored as JSON, so older versions may lack newer keys.
  model_params: { max_output_tokens?: number | null };
  memory_config: Partial<MemoryConfig>;
  limits: Partial<Limits>;
  tools: ToolAssignmentRead[];
};

export type AgentListItem = {
  id: string;
  name: string;
  description: string | null;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
  current_version: VersionSummary | null;
};

export type AgentRead = Omit<AgentListItem, "current_version"> & {
  current_version: VersionRead | null;
};

export type ToolAssignmentInput = {
  tool_key: string;
  requires_approval: boolean;
  config: Record<string, unknown>;
};

/** What the API accepts for one version of an agent. */
export type AgentConfigInput = {
  provider: LLMProvider;
  model: string;
  system_instructions: string;
  objectives: string | null;
  model_params: { max_output_tokens: number | null };
  memory_config: MemoryConfig;
  limits: Limits;
  tools: ToolAssignmentInput[];
};
