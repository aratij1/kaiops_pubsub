import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Live backend is required");

test("every dashboard attention count has a visible work item", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();

  const lane = page.locator(".oh-lane.needs-you");
  await expect(lane).toBeVisible({ timeout: 45_000 });
  const count = Number(await lane.locator("header em").textContent());
  const items = lane.locator(".oh-work-item");
  if (count > 0) {
    await expect(items.first()).toBeVisible();
    expect(await items.count()).toBeGreaterThan(0);
    expect(await items.count()).toBeLessThanOrEqual(count);
  } else {
    await expect(lane.getByText("Nothing needs your decision")).toBeVisible();
  }
});
