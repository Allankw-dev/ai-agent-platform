/** Fake Supabase and API payloads shared by the Playwright tests and a unit test that proves
 * the real supabase-js client accepts them. */

const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");

export const USER_ID = "11111111-1111-4111-8111-111111111111";

export function fakeJwt(email: string, expiresInSeconds = 3600): string {
  const now = Math.floor(Date.now() / 1000);
  const header = encode({ alg: "ES256", typ: "JWT", kid: "test" });
  const payload = encode({
    sub: USER_ID,
    email,
    role: "authenticated",
    aud: "authenticated",
    iat: now,
    exp: now + expiresInSeconds,
  });
  return `${header}.${payload}.signature`;
}

/** Body of POST /auth/v1/token?grant_type=password. */
export function passwordGrantResponse(email: string) {
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: fakeJwt(email),
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    refresh_token: "refresh-token",
    user: {
      id: USER_ID,
      aud: "authenticated",
      role: "authenticated",
      email,
      email_confirmed_at: new Date().toISOString(),
      app_metadata: { provider: "email" },
      user_metadata: {},
      created_at: new Date().toISOString(),
    },
  };
}

export const profile = (email: string) => ({
  id: USER_ID,
  email,
  full_name: null,
  avatar_url: null,
  is_super_admin: false,
  created_at: "2026-11-07T10:00:00Z",
});

export const organization = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "Acme Inc",
  slug: "acme-inc",
  created_at: "2026-11-07T10:00:00Z",
  role: "owner",
};

/** Body of POST /auth/v1/signup when the project requires email confirmation (no session). */
export function signUpNeedsConfirmationResponse(email: string) {
  return {
    id: USER_ID,
    aud: "authenticated",
    role: "",
    email,
    phone: "",
    confirmation_sent_at: new Date().toISOString(),
    app_metadata: { provider: "email", providers: ["email"] },
    user_metadata: {},
    identities: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}
