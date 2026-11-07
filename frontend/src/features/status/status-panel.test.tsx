import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiUnreachableError, getReadiness, type Readiness } from "@/lib/api";
import { StatusPanel } from "@/features/status/status-panel";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getReadiness: vi.fn(),
}));

const mockedGetReadiness = vi.mocked(getReadiness);

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StatusPanel />
    </QueryClientProvider>,
  );
}

const ready: Readiness = { status: "ready", checks: { database: true, redis: true } };

beforeEach(() => {
  mockedGetReadiness.mockReset();
});

describe("StatusPanel", () => {
  it("shows every service as operational when the API is ready", async () => {
    mockedGetReadiness.mockResolvedValue(ready);
    renderPanel();
    expect(await screen.findByText("All systems operational")).toBeInTheDocument();
    expect(screen.getAllByText("Operational")).toHaveLength(3);
  });

  it("marks only the failing dependency as down", async () => {
    mockedGetReadiness.mockResolvedValue({
      status: "unavailable",
      checks: { database: true, redis: false },
    });
    renderPanel();
    expect(await screen.findByText("Some services are down")).toBeInTheDocument();
    expect(screen.getAllByText("Operational")).toHaveLength(2);
    expect(screen.getAllByText("Down")).toHaveLength(1);
  });

  it("explains when the API cannot be reached", async () => {
    mockedGetReadiness.mockRejectedValue(new ApiUnreachableError());
    renderPanel();
    expect(await screen.findByText(/API unreachable/)).toBeInTheDocument();
    expect(screen.getByText("Down")).toBeInTheDocument();
    expect(screen.getAllByText("Unknown")).toHaveLength(2);
  });

  it("re-checks when the button is clicked", async () => {
    mockedGetReadiness.mockResolvedValue(ready);
    renderPanel();
    await screen.findByText("All systems operational");
    expect(mockedGetReadiness).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(mockedGetReadiness).toHaveBeenCalledTimes(2));
  });
});
