import { expect, test } from "@playwright/test";

const liveAlertId = String(process.env.KAIOPS_LIVE_ALERT_ID || "").trim();

test.skip(!process.env.KAIOPS_LIVE_E2E || !liveAlertId, "Set KAIOPS_LIVE_E2E=1 and KAIOPS_LIVE_ALERT_ID to verify a persisted live RCA");

test("completed live analysis renders its persisted RCA", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`/?workspace=alert&alert_id=${encodeURIComponent(liveAlertId)}`);
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.locator(".alert-details-cockpit")).toBeVisible({ timeout: 45_000 });
  const sections = page.getByRole("tablist", { name: "Incident workspace sections" });
  await sections.getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  await page.getByRole("tab", { name: /Summary/ }).click();

  const explanation = page.locator(".leading-explanation h4");
  await expect(explanation).toBeVisible({ timeout: 45_000 });
  await expect(explanation).not.toHaveText("A probable cause has not been established.");
  await expect(explanation).not.toContainText("RCA pending");
  await expect(page.getByText(/HTTP 401|Not authenticated/)).toHaveCount(0);
  await expect(page.getByText(/HTTP 502|All connection attempts failed/)).toHaveCount(0);
});
