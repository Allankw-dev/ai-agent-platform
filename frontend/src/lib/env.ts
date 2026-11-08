/** Base URL of the backend API. Public by design: it is not a secret. */
export const apiBaseUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

// Both values are meant for the browser. The publishable key is safe to expose; never put a
// Supabase secret key in NEXT_PUBLIC_ variables. Each variable is referenced literally so
// Next.js can inline it into the client bundle.
export const supabaseUrl = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").replace(/\/$/, "");
export const supabasePublishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";
