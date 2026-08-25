import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Set KAIOPS_LIVE_E2E=1 to run against a live API stack");

test("live regenerate RCA completes or reports its backend state", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/");
  const username = page.getByLabel("Username");
  if (await username.isVisible().catch(() => false)) {
    await username.fill(process.env.KAIOPS_E2E_USERNAME || "admin");
    await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
    await page.getByRole("button", { name: "Sign In" }).click();
  }
  const row = page.locator(".alert-stream-table tbody tr.alert-row").first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.click();
  const button = page.getByRole("button", { name: "Regenerate RCA For This Alert" });
  await expect(button).toBeVisible({ timeout: 30_000 });
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/api-gateway/alerts") && response.request().method() === "POST",
    { timeout: 30_000 },
  );
  await button.click();
  const response = await responsePromise;
  expect(response.ok()).toBeTruthy();
  await expect(page.getByText(/RCA regeneration (complete|triggered)|Analysis is still warming up/)).toBeVisible({
    timeout: 120_000,
  });
});
