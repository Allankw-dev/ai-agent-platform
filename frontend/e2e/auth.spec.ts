import { expect, test, type Page } from "@playwright/test";

import {
  organization,
  passwordGrantResponse,
  profile,
  signUpNeedsConfirmationResponse,
} from "./fixtures";
import { mockJson } from "./helpers";

// The build uses a placeholder Supabase project (see CI), and every network call is stubbed.
const EMAIL = "ada@example.com";

async function stubSignedInBackend(page: Page) {
  await mockJson(page, "**/auth/v1/token*", passwordGrantResponse(EMAIL));
  await mockJson(page, "**/auth/v1/logout*", null, 204);
  await mockJson(page, "**/api/v1/auth/me", profile(EMAIL));
  await mockJson(page, "**/api/v1/organizations?*", {
    items: [organization],
    total: 1,
    limit: 100,
    offset: 0,
  });
}

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("a-password");
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("visitors are sent to sign in and remembered", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("invitation links require signing in first", async ({ page }) => {
  await page.goto("/invite/some-token");
  await expect(page).toHaveURL(/\/login\?next=%2Finvite%2Fsome-token$/);
});

test("the sign-in form explains what is missing", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter your email address.")).toBeVisible();
  await expect(page.getByText("Enter your password.")).toBeVisible();
});

test("signing in leads to the dashboard with the user's organizations", async ({ page }) => {
  await stubSignedInBackend(page);
  await signIn(page);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Your organizations" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Acme Inc/ })).toBeVisible();
});

test("signing in from an invitation link returns to the invitation", async ({ page }) => {
  await stubSignedInBackend(page);
  await page.goto("/invite/some-token");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("a-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/invite\/some-token$/);
  await expect(page.getByRole("heading", { name: "You have been invited" })).toBeVisible();
});

test("signing out returns to the home page", async ({ page }) => {
  await stubSignedInBackend(page);
  await signIn(page);
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("creating an account asks the user to check their email", async ({ page }) => {
  await mockJson(page, "**/auth/v1/signup*", signUpNeedsConfirmationResponse(EMAIL));
  await page.goto("/register");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill("long-enough-1");
  await page.getByLabel("Repeat password").fill("long-enough-1");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
});

test("a password mismatch is caught before anything is sent", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill("long-enough-1");
  await page.getByLabel("Repeat password").fill("long-enough-2");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("The passwords do not match.")).toBeVisible();
});

test("an expired email link explains itself", async ({ page }) => {
  await page.goto("/auth/callback#error=access_denied&error_description=Email+link+has+expired");
  await expect(page.getByText("Email link has expired")).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to sign in" })).toBeVisible();
});
