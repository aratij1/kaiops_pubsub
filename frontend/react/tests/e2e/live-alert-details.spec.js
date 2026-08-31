import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Set KAIOPS_LIVE_E2E=1 to run against a live API stack");

test("live alert row opens the details cockpit", async ({ page }) => {
  test.setTimeout(120_000);
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/");
  const username = page.getByLabel("Username");
  await expect(username).toBeVisible({ timeout: 30_000 });
  await username.fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  const loginResponsePromise = page.waitForResponse((response) => response.url().includes("/api-gateway/auth/login"));
  await page.getByRole("button", { name: /sign in/i }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok(), `login returned HTTP ${loginResponse.status()}`).toBeTruthy();

  await expect(page.locator(".app-layout")).toBeVisible({ timeout: 30_000 });
  await page.goto("/alerts");
  await expect(page.getByRole("heading", { name: "Alert Stream" })).toBeVisible({ timeout: 30_000 });
  const openAlert = page.getByRole("button", { name: /Open in Unified Inbox|Review alert|View audit details/ }).first();
  await expect(openAlert).toBeVisible({ timeout: 30_000 });
  await openAlert.click();
  await expect(page.locator(".incident-command, .alert-details-cockpit").first()).toBeVisible({ timeout: 30_000 });
  expect(pageErrors).toEqual([]);
});
