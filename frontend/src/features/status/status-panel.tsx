"use client";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiUnreachableError, getReadiness } from "@/lib/api";

type ServiceState = "operational" | "down" | "unknown";

function ServiceBadge({ state }: { state: ServiceState }) {
  if (state === "operational") return <Badge variant="success">Operational</Badge>;
  if (state === "down") return <Badge variant="danger">Down</Badge>;
  return <Badge variant="muted">Unknown</Badge>;
}

export function StatusPanel() {
  const query = useQuery({
    queryKey: ["readiness"],
    queryFn: ({ signal }) => getReadiness(signal),
    refetchInterval: 15_000,
  });

  const data = query.data;
  const apiState: ServiceState = data ? "operational" : query.isError ? "down" : "unknown";
  const dependencyState = (ok: boolean | undefined): ServiceState =>
    ok === undefined ? "unknown" : ok ? "operational" : "down";

  const services: { name: string; description: string; state: ServiceState }[] = [
    { name: "API", description: "The backend service", state: apiState },
    { name: "Database", description: "PostgreSQL", state: dependencyState(data?.checks.database) },
    { name: "Queue", description: "Redis", state: dependencyState(data?.checks.redis) },
  ];

  let summary = "Checking services…";
  if (data?.status === "ready") summary = "All systems operational";
  else if (data?.status === "unavailable") summary = "Some services are down";
  else if (query.isError) {
    summary =
      query.error instanceof ApiUnreachableError
        ? "API unreachable: the backend is not running or cannot be reached"
        : "The API returned an unexpected response";
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p role="status" className="text-lg font-medium">
          {summary}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCw aria-hidden className={query.isFetching ? "size-4 animate-spin" : "size-4"} />
          {query.isFetching ? "Checking…" : "Check again"}
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        {services.map((service) => (
          <Card key={service.name}>
            <CardHeader>
              <CardTitle>{service.name}</CardTitle>
              <CardDescription>{service.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <ServiceBadge state={service.state} />
            </CardContent>
          </Card>
        ))}
      </div>

      {query.dataUpdatedAt > 0 && (
        <p className="text-xs text-muted-foreground">
          Last checked {new Date(query.dataUpdatedAt).toLocaleTimeString()}. Refreshes every 15
          seconds.
        </p>
      )}
    </div>
  );
}
