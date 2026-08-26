import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const json = (payload) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(payload),
});

const routes = [
  ["/", "Operations Overview", ".operations-home"],
  ["/alerts", "Alert Stream", ".ingestion-stream-page"],
  ["/incidents", "Unified Inbox", ".operations-center"],
  ["/approvals", "Approvals", ".approval-workspace"],
  ["/copilot", "Kai Intelligence", ".copilot-workspace"],
  ["/agent-flow", "Kai Trace", ".agent-flow-workspace"],
  ["/knowledge", "Knowledge", ".ai-hub"],
  ["/gateway-safety", "Gateway safety details", ".trust-center"],
  ["/audit", "Platform Health & Audit", ".governance-workspace.is-audit"],
  ["/closed-incidents", "Closed Incidents", ".resolution-history-workspace"],
  ["/applications", "Applications", ".applications-workspace"],
  ["/integrations", "Integration setup", ".onboarding-workspace"],
  ["/admin", "Platform Settings", ".platform-settings"],
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

test("desktop routed shell gives the Unified Inbox the full workspace", async ({ page }) => {
  await page.setViewportSize({ width: 1365, height: 768 });
  await mockPlatform(page);
  await signIn(page, "/incidents");
  await expect(page.getByRole("heading", { level: 1, name: "Unified Inbox" })).toBeVisible({ timeout: 30_000 });
  const inboxWorkspace = page.locator(".operations-center:visible");
  await expect(inboxWorkspace).toBeVisible();

  const geometry = await inboxWorkspace.evaluate((inboxElement) => {
    const rect = (element) => element.getBoundingClientRect();
    const routedFrame = inboxElement.closest(".kai-routed-frame");
    const workspaceElement = inboxElement.closest(".kai-workspace-frame");
    const shellElement = inboxElement.closest(".kai-shell");
    const shell = rect(shellElement);
    const workspace = rect(workspaceElement);
    const inbox = rect(inboxElement);
    const routedStyle = getComputedStyle(routedFrame);
    return {
      viewportWidth: window.innerWidth,
      shellLeft: shell.left,
      shellWidth: shell.width,
      workspaceWidth: workspace.width,
      inboxWidth: inbox.width,
      routedDisplay: routedStyle.display,
      routedColumns: routedStyle.gridTemplateColumns,
    };
  });

  expect(geometry.shellLeft).toBeLessThan(1);
  expect(geometry.shellWidth).toBeGreaterThan(geometry.viewportWidth - 20);
  expect(geometry.workspaceWidth).toBeGreaterThan(geometry.viewportWidth - 260);
  expect(geometry.inboxWidth).toBeGreaterThan(geometry.viewportWidth - 340);
  expect(geometry.routedDisplay).toBe("block");
  expect(geometry.routedColumns).toBe("none");
});

test("representative operational routes reflow and retain accessible semantics", async ({ page }) => {
  test.setTimeout(120_000);
  await mockPlatform(page);
  await signIn(page, "/incidents");
  await expect(page.getByRole("heading", { level: 1, name: "Unified Inbox" })).toBeVisible({ timeout: 30_000 });

  let results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((row) => ["serious", "critical"].includes(row.impact))).toEqual([]);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
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
  await expect(page.getByRole("heading", { level: 1, name: "Operations Overview" })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "artifacts/ui-redesign-command-center.png", fullPage: true });

  await page.getByRole("button", { name: "Capabilities", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Automation Capabilities" })).toBeVisible();
  await page.screenshot({ path: "artifacts/ui-redesign-automation.png", fullPage: true });

  await page.getByRole("button", { name: "Applications", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Applications" })).toBeVisible();
  await page.screenshot({ path: "artifacts/ui-redesign-onboarding.png", fullPage: true });

  await page.getByRole("button", { name: "Control Plane", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Platform Control Plane" })).toBeVisible();
  await page.screenshot({ path: "artifacts/ui-redesign-audit.png", fullPage: true });
});
