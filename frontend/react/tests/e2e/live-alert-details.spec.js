import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Set KAIOPS_LIVE_E2E=1 to run against a live API stack");

test("live alert row opens the details cockpit", async ({ page }) => {
  test.setTimeout(120_000);
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/");
  const username = page.getByLabel("Username");
  if (await username.isVisible().catch(() => false)) {
    await username.fill(process.env.KAIOPS_E2E_USERNAME || "admin");
    await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
    await page.getByRole("button", { name: "Sign In" }).click();
  }

  await expect(page.getByRole("heading", { name: "Alert Stream" })).toBeVisible({ timeout: 30_000 });
  const alertRows = page.locator(".alert-stream-table tbody tr.alert-row");
  await expect(alertRows.first()).toBeVisible({ timeout: 30_000 });
  const rowCount = await alertRows.count();
  for (let index = 0; index < rowCount; index += 1) {
    await alertRows.nth(index).click();
    await expect(page.getByRole("heading", { name: "Alert Details Cockpit" })).toBeVisible({ timeout: 15_000 });
  }
  expect(pageErrors).toEqual([]);
});
