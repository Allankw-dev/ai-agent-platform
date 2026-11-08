import { vi } from "vitest";

/** Fakes for the parts of supabase.auth the app uses. */
export const auth = {
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  resend: vi.fn(),
  resetPasswordForEmail: vi.fn(),
  updateUser: vi.fn(),
  exchangeCodeForSession: vi.fn(),
  getSession: vi.fn(),
};

export function resetSupabase() {
  for (const fn of Object.values(auth)) fn.mockReset();
  auth.getSession.mockResolvedValue({ data: { session: null } });
}

export async function supabaseFactory(importOriginal: () => Promise<Record<string, unknown>>) {
  const actual = await importOriginal();
  return {
    ...actual,
    isSupabaseConfigured: () => true,
    getSupabase: () => ({ auth }),
    getAccessToken: vi.fn(async () => "test-token"),
    signOut: vi.fn(async () => {}),
  };
}
