import { expect, test } from "@playwright/test";

const liveAlertId = String(process.env.KAIOPS_LIVE_ALERT_ID || "").trim();
const liveIncidentId = String(process.env.KAIOPS_LIVE_INCIDENT_ID || "").trim();

async function visibleConfidence(page) {
  const meter = page.getByRole("progressbar", { name: /Leading hypothesis confidence|Confirmed RCA confidence/ });
  await expect(meter).toBeVisible({ timeout: 45_000 });
  const label = await meter.getAttribute("aria-label");
  const value = Number(await meter.getAttribute("aria-valuenow"));
  expect(value, `expected a positive ${label} percentage`).toBeGreaterThan(0);
  return { label, value };
}

test.skip(!process.env.KAIOPS_LIVE_E2E || !liveAlertId, "Set KAIOPS_LIVE_E2E=1 and KAIOPS_LIVE_ALERT_ID to run against a live API stack");

test("live fresh RCA stays authenticated and renders the persisted analysis", async ({ page }) => {
  test.setTimeout(360_000);
  const analysisRequests = [];
  const analysisResponses = [];
  page.on("request", (request) => {
    if (request.url().includes("/api-gateway/analysis/")) {
      analysisRequests.push({ url: request.url(), authorization: request.headers().authorization || "" });
    }
  });
  page.on("response", (response) => {
    if (response.url().includes("/api-gateway/analysis/")) {
      analysisResponses.push({ url: response.url(), status: response.status() });
    }
  });

  await page.goto(`/?workspace=alert&alert_id=${encodeURIComponent(liveAlertId)}`);
  const username = page.getByLabel("Username");
  await expect(username).toBeVisible({ timeout: 30_000 });
  await username.fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  const loginResponsePromise = page.waitForResponse((response) => response.url().includes("/api-gateway/auth/login"));
  await page.getByRole("button", { name: /sign in/i }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok(), `login returned HTTP ${loginResponse.status()}`).toBeTruthy();
  await expect(page.locator(".app-layout")).toBeVisible({ timeout: 45_000 });

  await expect(page.locator(".alert-details-cockpit")).toBeVisible({ timeout: 45_000 });
  const tabs = page.getByRole("tablist", { name: "Incident workspace sections" });
  await tabs.getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  await page.getByRole("button", { name: /Fresh context/ }).click();
  await page.getByRole("button", { name: "Run fresh analysis" }).click();

  await expect(page.getByText(new RegExp(`Fresh context and RCA analysis completed for alert ${liveAlertId}|Analysis for alert ${liveAlertId} is still running in the backend`))).toBeVisible({ timeout: 330_000 });
  await expect(page.getByText(/HTTP 401|Not authenticated/)).toHaveCount(0);
  expect(analysisRequests.some(({ url }) => url.includes(`/analysis/alerts/${liveAlertId}/regenerate`))).toBeTruthy();
  const orchestrationRequests = analysisRequests.filter(({ url }) => url.includes(`/analysis/alerts/${liveAlertId}/regenerate`)
    || url.includes("/analysis/context/collect")
    || url.includes("/analysis/resolution/resolve"));
  expect(orchestrationRequests).toHaveLength(1);
  expect(analysisRequests.every(({ authorization }) => authorization.startsWith("Bearer "))).toBeTruthy();
  expect(analysisResponses.filter(({ url }) => url.includes(`/analysis/alerts/${liveAlertId}/regenerate`)).every(({ status }) => status >= 200 && status < 300)).toBeTruthy();

  const workspaceConfidence = await visibleConfidence(page);
  expect(workspaceConfidence.label).toBe("Leading hypothesis confidence");
  await expect(page.getByText("This is a diagnostic hypothesis score, not a confirmed RCA or execution permission.")).toBeVisible();

  if (liveIncidentId) {
    await page.goto(`/incidents/${encodeURIComponent(liveIncidentId)}`);
    const incidentConfidence = page.locator(".ic-confidence");
    await expect(incidentConfidence).toBeVisible({ timeout: 45_000 });
    await expect(incidentConfidence).toContainText("Leading hypothesis confidence");
    const incidentText = await incidentConfidence.innerText();
    expect(Number(incidentText.match(/(\d+)%/)?.[1])).toBe(workspaceConfidence.value);
    await incidentConfidence.locator("xpath=ancestor::section").getByText("Why this confidence?").click();
    await expect(page.getByText("The investigation is not conclusive; this score cannot authorize remediation.")).toBeVisible();
  }
});
