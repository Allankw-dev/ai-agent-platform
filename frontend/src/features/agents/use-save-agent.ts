"use client";

import { useState } from "react";

import {
  sameConfig,
  toAgentConfig,
  valuesFromAgent,
  type AgentFormValues,
} from "@/features/agents/agent-form-model";
import { useCreateVersion, useUpdateAgent } from "@/lib/api/queries";
import type { AgentRead } from "@/lib/api/types";

export type SaveResult = "saved" | "unchanged" | "failed";

/**
 * Saves the edit form. Behavior changes become a new version; name and description are updated
 * on the agent itself. Only what actually changed is sent.
 */
export function useSaveAgent(orgId: string, agent: AgentRead) {
  const createVersion = useCreateVersion(orgId, agent.id);
  const updateAgent = useUpdateAgent(orgId, agent.id);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  async function save(values: AgentFormValues): Promise<SaveResult> {
    setError(null);
    const before = valuesFromAgent(agent);
    const config = toAgentConfig(values);
    const configChanged = !sameConfig(config, toAgentConfig(before));

    const name = values.name.trim();
    const description = values.description.trim() || null;
    const nameChanged = name !== agent.name;
    const descriptionChanged = description !== agent.description;
    if (!configChanged && !nameChanged && !descriptionChanged) return "unchanged";

    setPending(true);
    let savedVersion = false;
    try {
      if (configChanged) {
        await createVersion.mutateAsync({
          config,
          change_note: values.changeNote.trim() || null,
        });
        savedVersion = true;
      }
      if (nameChanged || descriptionChanged) {
        await updateAgent.mutateAsync({
          ...(nameChanged ? { name } : {}),
          ...(descriptionChanged ? { description } : {}),
        });
      }
      return "saved";
    } catch (caught) {
      const reason = caught instanceof Error ? caught.message : "Something went wrong.";
      setError(
        savedVersion
          ? new Error(`The new version was saved, but the name or description was not: ${reason}`)
          : caught,
      );
      return "failed";
    } finally {
      setPending(false);
    }
  }

  return { save, pending, error };
}
