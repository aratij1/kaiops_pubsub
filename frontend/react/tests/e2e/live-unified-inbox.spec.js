import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Live backend is required");

test("canonical actionable incidents and counters use the same inbox projection", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/incidents");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();

  const tableRows = page.locator(".incident-summary-table tbody tr");
  await expect(tableRows.first()).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("No incidents match this view.", { exact: true })).toHaveCount(0);
  await expect(tableRows).toHaveCount(10);

  const totals = page.locator('[aria-label="Incident totals"] strong');
  const active = Number(await totals.nth(1).textContent());
  const total = Number(await totals.nth(2).textContent());
  expect(active).toBeGreaterThan(0);
  expect(active).toBeLessThanOrEqual(total);

  for (const badge of await page.locator(".incident-summary-table tbody .pill").allTextContents()) {
    expect(badge.trim().toLowerCase()).not.toBe("warning");
  }
});
