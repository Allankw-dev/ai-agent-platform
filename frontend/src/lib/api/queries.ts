"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/features/auth/auth-provider";
import { apiFetch } from "@/lib/api-client";
import type {
  Invitation,
  InvitationAccepted,
  InvitationCreated,
  Member,
  OrgRole,
  Organization,
  Page,
  UserProfile,
} from "@/lib/api/types";

export const keys = {
  me: ["me"] as const,
  orgs: ["orgs"] as const,
  org: (id: string) => ["org", id] as const,
  members: (id: string, limit: number) => ["members", id, limit] as const,
  invitations: (id: string, limit: number) => ["invitations", id, limit] as const,
};

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
