import { expect, test } from "@playwright/test";

const incidentId = String(process.env.KAIOPS_LIVE_INCIDENT_ID || "").trim();

test.skip(!process.env.KAIOPS_LIVE_E2E || !incidentId, "Set a live incident ID for release validation");

test("production incident renders durable context enrichment without raw Not Found", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  await page.goto(`/incidents/${encodeURIComponent(incidentId)}`);
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.getByRole("heading", { name: "Evidence gaps and human requests" })).toBeVisible({
    timeout: 45_000,
  });
  await expect(page.getByText("Not Found", { exact: true })).toHaveCount(0);
  await expect(page.locator(".context-enrichment-list article").first()).toBeVisible();
  await expect(page.getByText(/no durable work items were created/i)).toHaveCount(0);
  await expect(page.getByText(/Release [a-f0-9]{12}/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("incident-context-enrichment.png"), fullPage: true });
});
