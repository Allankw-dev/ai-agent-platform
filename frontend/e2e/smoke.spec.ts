import { expect, test } from "@playwright/test";

// The backend is stubbed at the network layer, so these tests need only the frontend.
const READY = { status: "ready", checks: { database: true, redis: true } };

test("landing page loads and navigates to the status page", async ({ page }) => {
  await page.route("**/api/v1/health/ready", (route) => route.fulfill({ json: READY }));

  await page.goto("/");
  await expect(
    page.getByRole("heading", { level: 1, name: /AI agents that do real work/ }),
  ).toBeVisible();

  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Status" })
    .click();
  await expect(page).toHaveURL(/\/status$/);
  await expect(page.getByRole("heading", { name: "System status" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("All systems operational");
});

test("status page reports a down dependency", async ({ page }) => {
  await page.route("**/api/v1/health/ready", (route) =>
    route.fulfill({
      status: 503,
      json: { status: "unavailable", checks: { database: true, redis: false } },
    }),
  );
  await page.goto("/status");
  await expect(page.getByRole("status")).toHaveText("Some services are down");
});

test("status page explains when the API is unreachable", async ({ page }) => {
  await page.route("**/api/v1/health/ready", (route) => route.abort());
  await page.goto("/status");
  await expect(page.getByRole("status")).toContainText("API unreachable");
});

test("check again button re-queries the API", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/v1/health/ready", (route) => {
    calls += 1;
    return route.fulfill({ json: READY });
  });
  await page.goto("/status");
  await expect(page.getByRole("status")).toHaveText("All systems operational");
  const before = calls;
  await page.getByRole("button", { name: "Check again" }).click();
  await expect.poll(() => calls).toBeGreaterThan(before);
});
