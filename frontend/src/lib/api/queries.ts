"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/features/auth/auth-provider";
import { apiFetch } from "@/lib/api-client";
import { followRunEvents } from "@/lib/run-events";
import type {
  AgentConfigInput,
  AgentListItem,
  AgentRead,
  AgentStatus,
  Approval,
  ApprovalStatus,
  Integration,
  IntegrationProvider,
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
  integrations: (orgId: string) => ["integrations", orgId] as const,
  integrationList: (orgId: string, limit: number) => ["integrations", orgId, limit] as const,
  approvals: (orgId: string) => ["approvals", orgId] as const,
  approvalList: (orgId: string, filters: ApprovalFilters) =>
    ["approvals", orgId, "list", filters] as const,
  approval: (orgId: string, approvalId: string) => ["approvals", orgId, "one", approvalId] as const,
  pendingApprovals: (orgId: string) => ["approvals", orgId, "pending-count"] as const,
};

export type ApprovalFilters = { status?: ApprovalStatus; limit: number };

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

/** While the live stream is connected the page is told what changes, so it only double-checks. */
export const RUN_SAFETY_POLL_MS = 30_000;
/** Events that arrive together (a step starting, finishing) cause one refresh, not several. */
const REFRESH_AFTER_EVENT_MS = 150;

/**
 * Follows a run live while it is still going: each event it receives refreshes the run, and
 * `onConnection` says whether the connection is open. It never throws and needs nothing else from
 * the caller; if live updates are not possible, regular polling (see useRun) keeps the page right.
 */
function useFollowRun(
  orgId: string,
  runId: string,
  following: boolean,
  onConnection: (connected: boolean) => void,
) {
  const client = useQueryClient();
  const refresh = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!following) return;
    const controller = new AbortController();
    void followRunEvents({
      orgId,
      runId,
      signal: controller.signal,
      onConnection,
      onEvent: () => {
        if (refresh.current) return; // a refresh is already on its way
        refresh.current = setTimeout(() => {
          refresh.current = null;
          void client.invalidateQueries({ queryKey: keys.run(orgId, runId) });
        }, REFRESH_AFTER_EVENT_MS);
      },
    });
    return () => {
      controller.abort();
      if (refresh.current) clearTimeout(refresh.current);
      refresh.current = null;
      onConnection(false);
    };
  }, [client, orgId, runId, following, onConnection]);
}

/**
 * One run with its steps. It updates the moment something happens (live stream), and checks every
 * couple of seconds as a fallback while the stream is not connected, until the run has finished.
 */
export function useRun(orgId: string, runId: string) {
  const enabled = useEnabled();
  const [live, setLive] = useState(false);
  const query = useQuery({
    queryKey: keys.run(orgId, runId),
    queryFn: () => apiFetch<RunDetail>(`/organizations/${orgId}/runs/${runId}`),
    enabled,
    refetchInterval: (q) =>
      isActiveRun(q.state.data?.status) ? (live ? RUN_SAFETY_POLL_MS : RUN_POLL_MS) : false,
  });
  useFollowRun(orgId, runId, enabled && isActiveRun(query.data?.status), setLive);
  return query;
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

// ---------- integrations ----------

/**
 * Only call this for people who may view integrations (the API refuses members). Pass
 * `active = false` to skip the request when nothing on screen needs the list.
 */
export function useIntegrations(orgId: string, limit: number, active = true) {
  const enabled = useEnabled() && active;
  return useQuery({
    queryKey: keys.integrationList(orgId, limit),
    queryFn: () =>
      apiFetch<Page<Integration>>(`/organizations/${orgId}/integrations`, { query: { limit } }),
    enabled,
  });
}

export function useCreateIntegration(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      provider: IntegrationProvider;
      name: string;
      config: Record<string, unknown>;
    }) =>
      apiFetch<Integration>(`/organizations/${orgId}/integrations`, {
        method: "POST",
        body: input,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.integrations(orgId) }),
  });
}

export function useUpdateIntegration(orgId: string, integrationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      name?: string;
      status?: "active" | "disabled";
      config?: Record<string, unknown>;
    }) =>
      apiFetch<Integration>(`/organizations/${orgId}/integrations/${integrationId}`, {
        method: "PATCH",
        body: input,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.integrations(orgId) }),
  });
}

export function useDeleteIntegration(orgId: string, integrationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(`/organizations/${orgId}/integrations/${integrationId}`, {
        method: "DELETE",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.integrations(orgId) }),
  });
}

/**
 * Saving a secret is write-only: the request carries it, no response ever does. The component
 * that calls this must clear the typed value as soon as the request ends.
 */
export function useSaveSecret(orgId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { integrationId: string; secret: string }) =>
      apiFetch<Integration>(
        `/organizations/${orgId}/integrations/${input.integrationId}/credential`,
        { method: "PUT", body: { secret: input.secret } },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.integrations(orgId) }),
  });
}

export function useRemoveSecret(orgId: string, integrationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<void>(`/organizations/${orgId}/integrations/${integrationId}/credential`, {
        method: "DELETE",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.integrations(orgId) }),
  });
}

// ---------- approvals ----------

/** How often a list of waiting approvals, a waiting approval and the tab count are re-checked. */
export const APPROVAL_LIST_POLL_MS = 10_000;
export const APPROVAL_POLL_MS = 5_000;
export const APPROVAL_COUNT_POLL_MS = 30_000;

/** Only call this for people who may view approvals (the API refuses members). */
export function useApprovals(orgId: string, filters: ApprovalFilters) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.approvalList(orgId, filters),
    queryFn: () =>
      apiFetch<Page<Approval>>(`/organizations/${orgId}/approvals`, {
        query: { limit: filters.limit, status: filters.status },
      }),
    enabled,
    // Someone else may decide a waiting request, or one may expire: keep the list honest.
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === "pending")
        ? APPROVAL_LIST_POLL_MS
        : false,
  });
}

export function useApproval(orgId: string, approvalId: string) {
  const enabled = useEnabled();
  return useQuery({
    queryKey: keys.approval(orgId, approvalId),
    queryFn: () => apiFetch<Approval>(`/organizations/${orgId}/approvals/${approvalId}`),
    enabled,
    refetchInterval: (query) => (query.state.data?.status === "pending" ? APPROVAL_POLL_MS : false),
  });
}

/**
 * How many approvals are waiting, for the tab. `active` is false for people who may not view
 * approvals, so no request is made for them.
 */
export function usePendingApprovalCount(orgId: string, active: boolean) {
  const enabled = useEnabled() && active;
  return useQuery({
    queryKey: keys.pendingApprovals(orgId),
    queryFn: async () => {
      const page = await apiFetch<Page<Approval>>(`/organizations/${orgId}/approvals`, {
        query: { status: "pending", limit: 1 },
      });
      return page.total;
    },
    enabled,
    refetchInterval: APPROVAL_COUNT_POLL_MS,
  });
}

/**
 * Approve or reject one approval. The server decides once: a second click, or a late one, comes
 * back as an error with the reason, and the screen then refreshes to show what really happened.
 */
export function useDecideApproval(orgId: string, approvalId: string) {
  const client = useQueryClient();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: keys.approvals(orgId) }),
      client.invalidateQueries({ queryKey: keys.runs(orgId) }),
      client.invalidateQueries({ queryKey: ["run", orgId] }),
    ]);
  return useMutation({
    mutationFn: (input: { decision: "approve" | "reject"; note?: string }) =>
      apiFetch<Approval>(`/organizations/${orgId}/approvals/${approvalId}/${input.decision}`, {
        method: "POST",
        body: input.note ? { note: input.note } : undefined,
      }),
    onSuccess: refresh,
    onError: refresh,
  });
}
