import { expect, test } from "@playwright/test";

const liveAlertId = String(process.env.KAIOPS_LIVE_ALERT_ID || "").trim();
const liveIncidentId = String(process.env.KAIOPS_LIVE_INCIDENT_ID || "").trim();

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
  await page.getByText("Refresh analysis", { exact: true }).click();
  await page.getByLabel("Context strategy").selectOption("fresh");
  await page.getByRole("button", { name: "Run analysis" }).click();

  await expect(
    page.locator("main").getByText(
      new RegExp(`Fresh context and RCA analysis completed for alert ${liveAlertId}|Analysis for alert ${liveAlertId} is still running in the backend`),
    ).first(),
  ).toBeVisible({ timeout: 330_000 });
  await expect(page.getByText(/HTTP 401|Not authenticated/)).toHaveCount(0);
  expect(analysisRequests.some(({ url }) => url.includes(`/analysis/alerts/${liveAlertId}/regenerate`))).toBeTruthy();
  const orchestrationRequests = analysisRequests.filter(({ url }) => url.includes(`/analysis/alerts/${liveAlertId}/regenerate`)
    || url.includes("/analysis/context/collect")
    || url.includes("/analysis/resolution/resolve"));
  expect(orchestrationRequests).toHaveLength(1);
  expect(analysisRequests.every(({ authorization }) => authorization.startsWith("Bearer "))).toBeTruthy();
  expect(analysisResponses.filter(({ url }) => url.includes(`/analysis/alerts/${liveAlertId}/regenerate`)).every(({ status }) => status >= 200 && status < 300)).toBeTruthy();

  await page.getByRole("tab", { name: /Analysis Reasoning and options/ }).click();
  await expect(page.getByText(/Analysis:\s*insufficient evidence/i)).toBeVisible();
  await expect(page.getByText(/Missing evidence: traces/i)).toBeVisible();

  if (liveIncidentId) {
    await page.goto(`/incidents/${encodeURIComponent(liveIncidentId)}`);
    await expect(page.getByText(/Working hypothesis · RCA v\d+/)).toBeVisible();
    await expect(page.getByText(/Causal path is incomplete/)).toBeVisible();
    await expect(page.getByText(/No executable resolution is available/)).toBeVisible();
  }
});
