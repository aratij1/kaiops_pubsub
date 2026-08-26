import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Set KAIOPS_LIVE_E2E=1 to verify the deployed read-only inbox journey");

test("production Live Alerts link to Unified Inbox without persisted E2E records", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/alerts");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator(".kai-shell")).toBeVisible({ timeout: 30_000 });

  const linkedAlert = page.getByRole("button", { name: "Open in Unified Inbox" }).first();
  await expect(linkedAlert).toBeVisible({ timeout: 45_000 });
  await linkedAlert.click();
  await expect(page).toHaveURL(/\/incidents\/[0-9a-f-]+$/i);
  await expect(page.getByRole("heading", { name: "Unified Inbox" })).toBeVisible();

  await page.getByRole("button", { name: "Incident inbox" }).click();
  await expect(page.locator(".incident-list-heading").getByRole("heading", { name: "Unified Inbox" })).toBeVisible();
  await expect(page.locator(".unified-inbox-stack")).not.toContainText(/ServiceDown-E2E-|review-20\d{6}/i);
});
