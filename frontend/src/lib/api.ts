import { apiBaseUrl } from "@/lib/env";

export type Readiness = {
  status: "ready" | "unavailable";
  checks: { database: boolean; redis: boolean };
};

/** The API could not be reached at all (network error, server down, CORS). */
export class ApiUnreachableError extends Error {
  constructor(options?: ErrorOptions) {
    super("The API could not be reached.", options);
    this.name = "ApiUnreachableError";
  }
}

function isReadiness(value: unknown): value is Readiness {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const checks = v.checks as Record<string, unknown> | undefined;
  return (
    (v.status === "ready" || v.status === "unavailable") &&
    typeof checks === "object" &&
    checks !== null &&
    typeof checks.database === "boolean" &&
    typeof checks.redis === "boolean"
  );
}

/** Calls GET /api/v1/health/ready. A 503 is a valid answer ("a dependency is down"). */
export async function getReadiness(signal?: AbortSignal): Promise<Readiness> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/v1/health/ready`, { signal, cache: "no-store" });
  } catch (cause) {
    throw new ApiUnreachableError({ cause });
  }

  if (response.status !== 200 && response.status !== 503) {
    throw new Error(`Unexpected response from the API (HTTP ${response.status}).`);
  }

  const body: unknown = await response.json().catch(() => null);
  if (!isReadiness(body)) {
    throw new Error("The API returned an unexpected response format.");
  }
  return body;
}
