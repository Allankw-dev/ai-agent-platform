/**
 * Returns `next` only if it is a path inside this app. Anything else (other sites,
 * protocol-relative URLs, backslash tricks) is rejected, which prevents open redirects.
 */
export function safeNext(next: string | null | undefined): string | null {
  if (!next) return null;
  if (!next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  if (/[\u0000-\u001f]/.test(next)) return null;
  return next;
}
