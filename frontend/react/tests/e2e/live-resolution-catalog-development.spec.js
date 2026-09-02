import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Live backend is required");

test("knowledge development exposes safe cold-start catalog candidates", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/knowledge");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.getByRole("tab", { name: "Knowledge development" }).click();

  await expect(page.getByRole("heading", { name: "Resolution catalog development queue" })).toBeVisible({ timeout: 45_000 });
  const row = page.getByRole("row").filter({ hasText: "Read-only evidence collection" }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("draft");
  await expect(row).toContainText("independent sources");
});
