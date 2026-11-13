"use client";

import { useState } from "react";

import { ErrorNotice } from "@/components/error-notice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { ConfigSummary } from "@/features/agents/config-summary";
import { useAgentVersion, useAgentVersions, useRollbackAgent } from "@/lib/api/queries";
import type { VersionSummary } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const PAGE_SIZE = 20;

function VersionDetails({
  orgId,
  agentId,
  number,
}: {
  orgId: string;
  agentId: string;
  number: number;
}) {
  const version = useAgentVersion(orgId, agentId, number, true);
  return (
    <div className="border-t border-border bg-background/40 p-4">
      <ErrorNotice error={version.error} />
      {version.isPending && !version.error && <Spinner label="Loading version" />}
      {version.data && <ConfigSummary version={version.data} />}
    </div>
  );
}

type Props = {
  orgId: string;
  agentId: string;
  currentVersionId: string | null;
  canManage: boolean;
};

export function VersionHistory({ orgId, agentId, currentVersionId, canManage }: Props) {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [viewing, setViewing] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const versions = useAgentVersions(orgId, agentId, limit);
  const rollback = useRollbackAgent(orgId, agentId);

  function restore(version: VersionSummary) {
    rollback.mutate(version.version, { onSuccess: () => setConfirming(null) });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Version history</CardTitle>
        <CardDescription>
          Every change is saved as a new version. Restoring an older one makes it current again and
          deletes nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ErrorNotice error={versions.error ?? rollback.error} />
        {versions.isPending && !versions.error && <Spinner label="Loading versions" />}
        {versions.data && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {versions.data.items.map((version) => {
              const isCurrent = version.id === currentVersionId;
              const open = viewing === version.version;
              return (
                <li key={version.id}>
                  <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <div className="min-w-0 space-y-0.5">
                      <p className="text-sm font-medium">
                        Version {version.version}
                        {isCurrent && (
                          <Badge variant="success" className="ml-2">
                            Current
                          </Badge>
                        )}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {version.model} · {formatDateTime(version.created_at)}
                      </p>
                      {version.change_note && <p className="text-sm">{version.change_note}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-expanded={open}
                        aria-label={`${open ? "Hide" : "View"} version ${version.version}`}
                        onClick={() => setViewing(open ? null : version.version)}
                      >
                        {open ? "Hide" : "View"}
                      </Button>
                      {canManage &&
                        !isCurrent &&
                        (confirming === version.version ? (
                          <>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={rollback.isPending}
                              onClick={() => restore(version)}
                            >
                              Confirm restore
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                              Cancel
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="sm"
                            variant="outline"
                            aria-label={`Restore version ${version.version}`}
                            onClick={() => setConfirming(version.version)}
                          >
                            Restore
                          </Button>
                        ))}
                    </div>
                  </div>
                  {open && (
                    <VersionDetails orgId={orgId} agentId={agentId} number={version.version} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {versions.data && versions.data.total > versions.data.items.length && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setLimit((value) => value + PAGE_SIZE)}
          >
            Show more
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
