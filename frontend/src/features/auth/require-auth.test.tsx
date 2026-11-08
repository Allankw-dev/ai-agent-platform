import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RequireAuth } from "@/features/auth/require-auth";
import { authState, resetAuth } from "@/test/auth-mock";
import { nav, resetNavigation, router } from "@/test/next-navigation";

vi.mock("next/navigation", async () => (await import("@/test/next-navigation")).navigationMock);
vi.mock(
  "@/features/auth/auth-provider",
  async () => (await import("@/test/auth-mock")).authProviderMock,
);

beforeEach(() => {
  resetNavigation();
  resetAuth();
});

const renderGuard = () =>
  render(
    <RequireAuth>
      <p>secret area</p>
    </RequireAuth>,
  );

describe("RequireAuth", () => {
  it("shows the page to signed-in users", () => {
    renderGuard();
    expect(screen.getByText("secret area")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("sends visitors to sign in and remembers where they were going", () => {
    authState.status = "unauthenticated";
    nav.pathname = "/orgs/123/members";
    renderGuard();
    expect(screen.queryByText("secret area")).not.toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith("/login?next=%2Forgs%2F123%2Fmembers");
  });

  it("shows nothing sensitive and does not redirect while the session loads", () => {
    authState.status = "loading";
    renderGuard();
    expect(screen.queryByText("secret area")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("explains a missing configuration instead of redirecting forever", () => {
    authState.configured = false;
    authState.status = "unauthenticated";
    renderGuard();
    expect(screen.getByRole("alert")).toHaveTextContent(/not configured/);
    expect(router.replace).not.toHaveBeenCalled();
  });
});
