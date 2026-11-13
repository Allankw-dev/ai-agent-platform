"use client";

import { useState } from "react";
import Link from "next/link";

import { ErrorNotice } from "@/components/error-notice";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { AgentStatusBadge } from "@/features/agents/agent-status-badge";
import { useCurrentOrg } from "@/features/orgs/org-context";
import { useAgents } from "@/lib/api/queries";
import type { AgentStatus } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { canManageAgents } from "@/lib/permissions";

const PAGE_SIZE = 20;
const STATUS_OPTIONS: { value: AgentStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "active", label: "Active" },
  { value: "disabled", label: "Disabled" },
];

export function AgentsListPage() {
  const org = useCurrentOrg();
  const mayManage = canManageAgents(org.role);
  const [status, setStatus] = useState<AgentStatus | "">("");
  const [searchText, setSearchText] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const agents = useAgents(org.id, { status: status || undefined, q: query || undefined, limit });
  const filtering = status !== "" || query !== "";

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Agents</h2>
          <p className="text-sm text-muted-foreground">
            {agents.data
              ? `${agents.data.total} ${agents.data.total === 1 ? "agent" : "agents"}${filtering ? " match" : ""}.`
              : "The agents in this organization."}
          </p>
        </div>
        {mayManage && (
          <Link href={`/orgs/${org.id}/agents/new`} className={buttonVariants()}>
            Create agent
          </Link>
        )}
      </div>

      <form
        role="search"
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setQuery(searchText.trim());
          setLimit(PAGE_SIZE);
        }}
      >
        <Input
          aria-label="Search agents by name"
          placeholder="Search by name"
          className="max-w-xs"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          maxLength={100}
        />
        <Button type="submit" variant="outline">
          Search
        </Button>
        <Select
          aria-label="Filter by status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as AgentStatus | "");
            setLimit(PAGE_SIZE);
          }}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
        {filtering && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setStatus("");
              setSearchText("");
              setQuery("");
            }}
          >
            Clear filters
          </Button>
        )}
      </form>

      <ErrorNotice error={agents.error} />
      {agents.isPending && !agents.error && <Spinner label="Loading agents" />}

      {agents.data && agents.data.items.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{filtering ? "No agents match" : "No agents yet"}</CardTitle>
            <CardDescription>
              {filtering
                ? "Try a different search or clear the filters."
                : mayManage
                  ? "Create your first agent to get started."
                  : "Ask an owner, admin or developer to create one."}
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {agents.data && agents.data.items.length > 0 && (
        <ul className="space-y-3">
          {agents.data.items.map((agent) => (
            <li key={agent.id}>
              <Card className="transition-colors hover:border-accent/60">
                <CardContent className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Link
                        href={`/orgs/${org.id}/agents/${agent.id}`}
                        className="font-medium hover:text-accent"
                      >
                        {agent.name}
                      </Link>
                      <AgentStatusBadge status={agent.status} />
                    </div>
                    {agent.description && (
                      <p className="line-clamp-2 text-sm text-muted-foreground">
                        {agent.description}
                      </p>
                    )}
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {agent.current_version && (
                      <p>
                        v{agent.current_version.version} · {agent.current_version.model}
                      </p>
                    )}
                    <p>Updated {formatDateTime(agent.updated_at)}</p>
                  </div>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {agents.data && agents.data.total > agents.data.items.length && (
        <Button variant="outline" size="sm" onClick={() => setLimit((value) => value + PAGE_SIZE)}>
          Show more
        </Button>
      )}
    </div>
  );
}
