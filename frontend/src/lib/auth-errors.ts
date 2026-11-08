import { SupabaseNotConfiguredError } from "@/lib/supabase";

/** Turns a Supabase (or network) error into a message that is safe and useful to show. */
export function describeAuthError(error: unknown): string {
  if (error instanceof SupabaseNotConfiguredError) {
    return "Sign-in is not configured on this deployment.";
  }
  const { message = "", status } = (error ?? {}) as { message?: string; status?: number };
  const text = message.toLowerCase();

  if (text.includes("email not confirmed")) {
    return "Confirm your email first: open the link we sent you, then sign in.";
  }
  if (text.includes("invalid login credentials")) return "Incorrect email or password.";
  if (status === 429 || text.includes("rate limit") || text.includes("too many")) {
    return "Too many attempts. Wait a minute and try again.";
  }
  if (text.includes("should be different from the old password")) {
    return "Choose a password you have not used before.";
  }
  if (text.includes("password") && text.includes("weak")) {
    return "That password is too easy to guess. Try a longer one.";
  }
  if (text.includes("fetch") || text.includes("network") || status === 0) {
    return "Could not reach the authentication service. Check your connection.";
  }
  return "Something went wrong. Please try again.";
}
