import { vi } from "vitest";

/** A controllable stand-in for next/navigation. Tests mutate `nav` and inspect `router`. */
export const router = {
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  refresh: vi.fn(),
  prefetch: vi.fn(),
};

export const nav = {
  params: {} as Record<string, string>,
  search: new URLSearchParams(),
  pathname: "/",
};

export function resetNavigation() {
  for (const fn of Object.values(router)) fn.mockReset();
  nav.params = {};
  nav.search = new URLSearchParams();
  nav.pathname = "/";
}

export const navigationMock = {
  useRouter: () => router,
  useParams: () => nav.params,
  useSearchParams: () => nav.search,
  usePathname: () => nav.pathname,
};
