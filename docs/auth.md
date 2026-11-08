# Sign-in and sessions

## How it works

- Accounts live in **Supabase Auth**. The browser talks to Supabase directly to register, sign in,
  confirm email and reset passwords (PKCE flow). The API never sees passwords.
- After sign-in the browser holds a short-lived access token and a refresh token (managed by
  supabase-js, auto-refreshed). Every API call sends `Authorization: Bearer <access token>`.
- The API verifies the token against Supabase's published public keys, then loads or creates the
  local profile. See `docs/tenancy.md` for what happens next.
- If the API answers 401, the app signs the user out.

## Pages

| Route | Purpose |
| --- | --- |
| `/register`, `/login`, `/forgot-password` | Account creation, sign-in, reset request |
| `/auth/callback` | Landing page for email links: exchanges the one-time code, then continues to `next` |
| `/reset-password` | Choose a new password (needs the session created by the reset link) |
| `/dashboard`, `/orgs/...`, `/profile`, `/invite/[token]` | Signed-in app (guarded by `RequireAuth`) |

`next` parameters are only followed if they are paths inside this app (`lib/safe-redirect.ts`),
which prevents open redirects.

## Supabase dashboard settings

- **Authentication > URL Configuration**: Site URL `http://localhost:3000` and the redirect URL
  `http://localhost:3000/**` (add your production URL when you deploy).
- Keep **email confirmation** on. Confirmation and reset links must be opened in the same browser
  that requested them (the PKCE verifier is stored there).
- Supabase's built-in email sender is rate limited and meant for development. Configure your own
  SMTP provider before real users sign up.

## Trade-offs to know

- Tokens are held by supabase-js in the browser's storage, so a cross-site scripting bug could
  read them. The mitigation is preventing XSS: React escapes output, and a strict
  Content-Security-Policy is planned for the hardening phase (Phase 8).
- Route guarding is client-side. That is acceptable because the API enforces authentication and
  authorization on every request; the guard only decides what to show.
- Never put a Supabase secret key in a `NEXT_PUBLIC_` variable. Only the publishable key belongs in
  the browser.
