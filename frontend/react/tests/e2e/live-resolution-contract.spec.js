import { expect, test } from "@playwright/test";

const incidentId = String(process.env.KAIOPS_LIVE_INCIDENT_ID || "").trim();

test.skip(!process.env.KAIOPS_LIVE_E2E || !incidentId, "Live incident id is required");

test("resolution shows only governed execution or an explicit unavailable state", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto(`/incidents/${encodeURIComponent(incidentId)}`);
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.locator(".incident-command")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Pending live executor - no command has been executed yet")).toHaveCount(0);

  const resolutionPanel = page.locator(".resolution-decision-brief");
  if (await resolutionPanel.count()) {
    const unavailable = page.getByRole("heading", { name: "No executable remediation script is available" });
    if (await unavailable.count()) {
      await expect(unavailable).toBeVisible();
      await expect(page.getByRole("button", { name: /Inspect safeguards and decide/ })).toBeDisabled();
    } else {
      await expect(page.getByText("Exact governed commands")).toBeVisible();
      await expect(page.locator(".resolution-script pre code")).not.toBeEmpty();
    }
  } else {
    await expect(page.getByRole("heading", { name: /No executable resolution is available|Resolution plan/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "No execution to control" })).toBeDisabled();
  }
});
