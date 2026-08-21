import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const json = (payload) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(payload),
});

const routes = [
  ["/", "Operations Overview", ".ro-page"],
  ["/alerts", "Alert Stream", ".ingestion-stream-page"],
  ["/incidents", "Incident Queue", ".operations-center"],
  ["/approvals", "My Approvals", ".approval-workspace"],
  ["/copilot", "KaiMS Assistant", ".copilot-workspace"],
  ["/agent-flow", "Technical Timeline", ".agent-flow-workspace"],
  ["/knowledge", "Knowledge & Runbooks", ".ai-hub"],
  ["/gateway-safety", "Gateway safety details", ".governance-workspace.is-safety"],
  ["/audit", "Platform Health & Audit", ".governance-workspace.is-audit"],
  ["/closed-incidents", "Closed Incidents", ".resolution-history-workspace"],
  ["/applications", "Projects & Integrations", ".applications-workspace"],
  ["/integrations", "Integration setup", ".onboarding-workspace"],
  ["/admin", "Users & Access", ".platform-settings"],
  ["/executive", "Reliability report", ".executive-workspace"],
];

async function mockPlatform(page) {
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    if (path === "/auth/config") return route.fulfill(json({ mode: "local", local_development_only: true }));
    if (path === "/auth/login") return route.fulfill(json({ access_token: "ui-token", refresh_token: "ui-refresh", user: { id: 1, username: "admin", role_name: "Administrator" } }));
    if (path === "/healthz") return route.fulfill(json({ status: "ok", service: "api-gateway" }));
    if (path === "/applications") return route.fulfill(json({ data: { rows: [] } }));
    return route.fulfill(json({ data: { rows: [] }, rows: [], summary: {}, items: [] }));
  });
}

async function signIn(page, path) {
  await page.goto(path);
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();
}

for (const [path, pageTitle, workspaceSelector] of routes) {
  test(`${pageTitle} uses the unified readable workspace`, async ({ page }) => {
    test.setTimeout(90_000);
    await mockPlatform(page);
    await signIn(page, path);
    await expect(page.getByRole("heading", { level: 1, name: pageTitle })).toBeVisible({ timeout: 30_000 });
    // React may retain a hidden Suspense/offscreen tree during lazy-route
    // transitions; assert the active workspace, not the implementation copy.
    await expect(page.locator(`${workspaceSelector}:visible`)).toBeVisible();
    await expect(page.locator(".content-area > .hero .subtitle")).not.toBeEmpty();
    const desktopOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(desktopOverflow).toBeFalsy();
  });
}

test("representative operational routes reflow and retain accessible semantics", async ({ page }) => {
  test.setTimeout(120_000);
  await mockPlatform(page);
  await signIn(page, "/incidents");
  await expect(page.getByRole("heading", { level: 1, name: "Incident Queue" })).toBeVisible({ timeout: 30_000 });

  let results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((row) => ["serious", "critical"].includes(row.impact))).toEqual([]);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Navigate to")).toBeVisible();
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(mobileOverflow).toBeFalsy();
  await expect(page.locator(".operations-center")).toBeVisible();
});

test("audit and safety controls communicate distinct purposes", async ({ page }) => {
  await mockPlatform(page);
  await signIn(page, "/audit");
  await expect(page.getByRole("heading", { name: "Policy decision audit trail" })).toBeVisible();
  await expect(page.getByText("Governance evidence", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gateway safety decisions" })).toHaveCount(0);
});

test("captures the redesigned product surfaces for visual review", async ({ page }) => {
  test.skip(!process.env.CAPTURE_UI_REDESIGN, "Visual review capture is opt-in.");
  test.setTimeout(120_000);
  await mockPlatform(page);
  await signIn(page, "/");
  await expect(page.getByRole("heading", { level: 1, name: "Operations Command Center" })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "artifacts/ui-redesign-command-center.png", fullPage: true });

  await page.getByRole("button", { name: "Automation", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Agent Automation" })).toBeVisible();
  await page.screenshot({ path: "artifacts/ui-redesign-automation.png", fullPage: true });

  await page.getByRole("button", { name: "Project Onboarding", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Project Onboarding" })).toBeVisible();
  await page.screenshot({ path: "artifacts/ui-redesign-onboarding.png", fullPage: true });

  await page.getByRole("button", { name: "Audit Trail", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Audit Trail" })).toBeVisible();
  await page.screenshot({ path: "artifacts/ui-redesign-audit.png", fullPage: true });
});
