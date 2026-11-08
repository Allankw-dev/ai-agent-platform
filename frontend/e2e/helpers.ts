import type { Page, Route } from "@playwright/test";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
};

/** Answers a cross-origin request (including the browser's preflight) with a JSON body. */
export async function mockJson(
  page: Page,
  url: string,
  body: unknown,
  status = 200,
): Promise<void> {
  await page.route(url, (route: Route) => {
    if (route.request().method() === "OPTIONS") {
      return route.fulfill({ status: 204, headers: CORS });
    }
    if (status === 204) return route.fulfill({ status, headers: CORS });
    return route.fulfill({
      status,
      headers: { ...CORS, "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  });
}
