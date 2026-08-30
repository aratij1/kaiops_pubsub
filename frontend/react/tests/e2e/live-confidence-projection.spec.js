import { expect, test } from "@playwright/test";

const alertId = String(process.env.KAIOPS_LIVE_ALERT_ID || "").trim();
const incidentId = String(process.env.KAIOPS_LIVE_INCIDENT_ID || "").trim();
const expectedConfidence = Number(process.env.KAIOPS_EXPECTED_CONFIDENCE_PERCENT || 0);

test.skip(
  !process.env.KAIOPS_LIVE_E2E || !alertId || !incidentId || !expectedConfidence,
  "Set live alert, incident, and expected confidence values to verify projection cache coherence",
);

test("processed-result refresh cannot restore stale nested confidence", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`/?workspace=alert&alert_id=${encodeURIComponent(alertId)}`);
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator(".alert-details-cockpit")).toBeVisible({ timeout: 45_000 });

  const tabs = page.getByRole("tablist", { name: "Incident workspace sections" });
  await tabs.getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  const confidence = page.getByRole("progressbar", { name: "Leading hypothesis confidence" });
  await expect(confidence).toHaveAttribute("aria-valuenow", String(expectedConfidence));

  await page.getByRole("button", { name: "Reload Alert Details" }).click();
  await expect(confidence).toHaveAttribute("aria-valuenow", String(expectedConfidence));

  await page.goto(`/incidents/${encodeURIComponent(incidentId)}`);
  const incidentConfidence = page.locator(".ic-confidence");
  await expect(incidentConfidence).toContainText("Leading hypothesis confidence", { timeout: 45_000 });
  await expect(incidentConfidence).toContainText(`${expectedConfidence}%`);
});
