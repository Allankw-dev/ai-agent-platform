/** Base URL of the backend API. Public by design: it is not a secret. */
export const apiBaseUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
