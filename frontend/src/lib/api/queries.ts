"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/features/auth/auth-provider";
import { apiFetch } from "@/lib/api-client";
import type {
  AgentConfigInput,
  AgentListItem,
  AgentRead,
  AgentStatus,
  Invitation,
  InvitationAccepted,
  InvitationCreated,
  Member,
  OrgRole,
  Organization,
  Page,
  RunDetail,
  RunRead,
  RunStatus,
  ToolInfo,
  UserProfile,
  VersionRead,
  VersionSummary,
} from "@/lib/api/types";

export const keys = {
  me: ["me"] as const,
  orgs: ["orgs"] as const,
  org: (id: string) => ["org", id] as const,
  members: (id: string, limit: number) => ["members", id, limit] as const,
  invitations: (id: string, limit: number) => ["invitations", id, limit] as const,
  tools: ["tools"] as const,
  agents: (orgId: string) => ["agents", orgId] as const,
  agentList: (orgId: string, filters: AgentFilters) => ["agents", orgId, filters] as const,
  agent: (orgId: string, agentId: string) => ["agent", orgId, agentId] as const,
  versions: (orgId: string, agentId: string, limit: number) =>
    ["agent-versions", orgId, agentId, limit] as const,
  version: (orgId: string, agentId: string, number: number) =>
    ["agent-version", orgId, agentId, number] as const,
  runs: (orgId: string) => ["runs", orgId] as const,
  runList: (orgId: string, filters: RunFilters) => ["runs", orgId, filters] as const,
  run: (orgId: string, runId: string) => ["run", orgId, runId] as const,
};

export type RunFilters = { agentId?: string; status?: RunStatus; limit: number };

export type AgentFilters = { status?: AgentStatus; q?: string; limit: number };

/** Queries only run once there is a signed-in user to call the API as. */
function useEnabled() {
  return useAuth().status === "authenticated";
}

export function useMe() {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.me,
    queryFn: () => apiFetch<UserProfile>("/auth/me"),
    enabled,
  });
}

export function useOrganizations() {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.orgs,
    queryFn: () => apiFetch<Page<Organization>>("/organizations", { query: { limit: 100 } }),
    enabled,
  });
}

export function useOrganization(orgId: string) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.org(orgId),
    queryFn: () => apiFetch<Organization>(`/organizations/${orgId}`),
    enabled,
  });
}

export function useMembers(orgId: string, limit: number) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.members(orgId, limit),
    queryFn: () => apiFetch<Page<Member>>(`/organizations/${orgId}/members`, { query: { limit } }),
    enabled,
  });
}

export function useInvitations(orgId: string, limit: number, enabledByRole: boolean) {
  const enabled = useEnabled() && enabledByRole;
  return useQuery({
    queryKey: keys.invitations(orgId, limit),
    queryFn: () =>
      apiFetch<Page<Invitation>>(`/organizations/${orgId}/invitations`, { query: { limit } }),
    enabled,
  });
}

export function useCreateOrganization() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; slug?: string }) =>
      apiFetch<Organization>("/organizations", { method: "POST", body: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.orgs }),
  });
}

export function useRenameOrganization(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      apiFetch<Organization>(`/organizations/${orgId}`, { method: "PATCH", body: { name } }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.org(orgId) }),
        client.invalidateQueries({ queryKey: keys.orgs }),
      ]);
    },
  });
}

export function useDeleteOrganization(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<void>(`/organizations/${orgId}`, { method: "DELETE" }),
    onSuccess: async () => {
      client.removeQueries({ queryKey: keys.org(orgId) });
      await client.invalidateQueries({ queryKey: keys.orgs });
    },
  });
}

export function useChangeRole(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { userId: string; role: OrgRole }) =>
      apiFetch<{ role: OrgRole }>(`/organizations/${orgId}/members/${input.userId}`, {
        method: "PATCH",
        body: { role: input.role },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["members", orgId] }),
  });
}

export function useRemoveMember(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      apiFetch<void>(`/organizations/${orgId}/members/${userId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["members", orgId] }),
        client.invalidateQueries({ queryKey: keys.orgs }),
      ]);
    },
  });
}

export function useCreateInvitation(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { email: string; role: OrgRole }) =>
      apiFetch<InvitationCreated>(`/organizations/${orgId}/invitations`, {
        method: "POST",
        body: input,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["invitations", orgId] }),
  });
}

export function useRevokeInvitation(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) =>
      apiFetch<void>(`/organizations/${orgId}/invitations/${invitationId}`, {
        method: "DELETE",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["invitations", orgId] }),
  });
}

export function useAcceptInvitation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      apiFetch<InvitationAccepted>("/invitations/accept", { method: "POST", body: { token } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.orgs }),
  });
}

// ---------- agents ----------

/** The global tool catalog. It only changes with a release, so it is cached for a while. */
export function useTools() {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.tools,
    queryFn: () => apiFetch<ToolInfo[]>("/tools"),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useAgents(orgId: string, filters: AgentFilters) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.agentList(orgId, filters),
    queryFn: () =>
      apiFetch<Page<AgentListItem>>(`/organizations/${orgId}/agents`, {
        query: { limit: filters.limit, status: filters.status, q: filters.q || undefined },
      }),
    enabled,
  });
}

export function useAgent(orgId: string, agentId: string) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.agent(orgId, agentId),
    queryFn: () => apiFetch<AgentRead>(`/organizations/${orgId}/agents/${agentId}`),
    enabled,
  });
}

export function useAgentVersions(orgId: string, agentId: string, limit: number) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.versions(orgId, agentId, limit),
    queryFn: () =>
      apiFetch<Page<VersionSummary>>(`/organizations/${orgId}/agents/${agentId}/versions`, {
        query: { limit },
      }),
    enabled,
  });
}

/** One version in full, loaded only when `open` (for the history's "View" panel). */
export function useAgentVersion(orgId: string, agentId: string, number: number, open: boolean) {
  const enabled = useEnabled() && open;
  return useQuery({
    queryKey: keys.version(orgId, agentId, number),
    queryFn: () =>
      apiFetch<VersionRead>(`/organizations/${orgId}/agents/${agentId}/versions/${number}`),
    enabled,
    staleTime: Infinity, // versions are immutable
  });
}

export function useCreateAgent(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; description: string | null; config: AgentConfigInput }) =>
      apiFetch<AgentRead>(`/organizations/${orgId}/agents`, { method: "POST", body: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.agents(orgId) }),
  });
}

export function useUpdateAgent(orgId: string, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      name?: string;
      description?: string | null;
      status?: "active" | "disabled";
    }) =>
      apiFetch<AgentRead>(`/organizations/${orgId}/agents/${agentId}`, {
        method: "PATCH",
        body: input,
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.agents(orgId) }),
        client.invalidateQueries({ queryKey: keys.agent(orgId, agentId) }),
      ]);
    },
  });
}

export function useDeleteAgent(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      apiFetch<void>(`/organizations/${orgId}/agents/${agentId}`, { method: "DELETE" }),
    onSuccess: async (_data, agentId) => {
      client.removeQueries({ queryKey: keys.agent(orgId, agentId) });
      await client.invalidateQueries({ queryKey: keys.agents(orgId) });
    },
  });
}

export function useDuplicateAgent(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (agentId: string) =>
      apiFetch<AgentRead>(`/organizations/${orgId}/agents/${agentId}/duplicate`, {
        method: "POST",
        body: {},
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.agents(orgId) }),
  });
}

/** Saving changed behavior never edits a version: it adds a new one and makes it current. */
export function useCreateVersion(orgId: string, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { config: AgentConfigInput; change_note: string | null }) =>
      apiFetch<VersionRead>(`/organizations/${orgId}/agents/${agentId}/versions`, {
        method: "POST",
        body: input,
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.agents(orgId) }),
        client.invalidateQueries({ queryKey: keys.agent(orgId, agentId) }),
        client.invalidateQueries({ queryKey: ["agent-versions", orgId, agentId] }),
      ]);
    },
  });
}

export function useRollbackAgent(orgId: string, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (version: number) =>
      apiFetch<AgentRead>(`/organizations/${orgId}/agents/${agentId}/rollback`, {
        method: "POST",
        body: { version },
      }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.agents(orgId) }),
        client.invalidateQueries({ queryKey: keys.agent(orgId, agentId) }),
        client.invalidateQueries({ queryKey: ["agent-versions", orgId, agentId] }),
      ]);
    },
  });
}

// ---------- runs ----------

const ACTIVE: RunStatus[] = ["queued", "running", "awaiting_approval"];
/** A run that is still going: it will change without anyone touching it. */
export const isActiveRun = (status: RunStatus | undefined) =>
  status !== undefined && ACTIVE.includes(status);

export const RUN_POLL_MS = 2_000;
const LIST_POLL_MS = 5_000;

export function useRuns(orgId: string, filters: RunFilters) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.runList(orgId, filters),
    queryFn: () =>
      apiFetch<Page<RunRead>>(`/organizations/${orgId}/runs`, {
        query: { limit: filters.limit, agent_id: filters.agentId, status: filters.status },
      }),
    enabled,
    // Keep the list fresh while anything on it is still running.
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => isActiveRun(run.status)) ? LIST_POLL_MS : false,
  });
}

/** One run with its steps. Re-checks every couple of seconds until the run has finished. */
export function useRun(orgId: string, runId: string) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.run(orgId, runId),
    queryFn: () => apiFetch<RunDetail>(`/organizations/${orgId}/runs/${runId}`),
    enabled,
    refetchInterval: (query) => (isActiveRun(query.state.data?.status) ? RUN_POLL_MS : false),
  });
}

/** `idempotencyKey` makes a double click return the same run instead of starting two. */
export function useStartRun(orgId: string, agentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { message: string; idempotencyKey: string }) =>
      apiFetch<RunRead>(`/organizations/${orgId}/agents/${agentId}/runs`, {
        method: "POST",
        body: { message: input.message },
        headers: { "Idempotency-Key": input.idempotencyKey },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs(orgId) }),
  });
}

export function useCancelRun(orgId: string, runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<RunRead>(`/organizations/${orgId}/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.run(orgId, runId) }),
        client.invalidateQueries({ queryKey: keys.runs(orgId) }),
      ]);
    },
  });
}
