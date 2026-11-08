import { Alert } from "@/components/ui/alert";

/** Shows an error from a query or mutation. Renders nothing when there is none. */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error && error.message ? error.message : "Something went wrong.";
  return <Alert variant="error">{message}</Alert>;
}
