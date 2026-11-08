import { vi } from "vitest";

export const ME = { id: "user-me", email: "me@example.com" };

/** The value useAuth() returns in tests. Mutate it before rendering. */
export const authState = {
  status: "authenticated" as "loading" | "authenticated" | "unauthenticated",
  configured: true,
  user: { ...ME } as { id: string; email: string } | null,
  session: null,
  signOut: vi.fn(async () => {}),
};

export function resetAuth() {
  authState.status = "authenticated";
  authState.configured = true;
  authState.user = { ...ME };
  authState.signOut.mockReset();
  authState.signOut.mockResolvedValue(undefined);
}

export const authProviderMock = {
  useAuth: () => authState,
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
};
