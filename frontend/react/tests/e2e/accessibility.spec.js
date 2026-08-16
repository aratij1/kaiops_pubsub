import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const json = (payload) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(payload),
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    if (path === "/auth/login") {
      await route.fulfill(json({
        access_token: "accessibility-token",
        refresh_token: "accessibility-refresh",
        user: { id: 1, username: "admin", role_name: "Administrator" },
      }));
      return;
    }
    if (path === "/healthz") {
      await route.fulfill(json({ status: "ok", service: "api-gateway" }));
      return;
    }
    await route.fulfill(json({ data: { rows: [] }, rows: [], summary: {}, items: [] }));
  });
});

test("login and primary workspace have no serious or critical accessibility violations", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");

  const loginResults = await new AxeBuilder({ page }).analyze();
  const severeLoginViolations = loginResults.violations.filter((row) => ["serious", "critical"].includes(row.impact));
  expect(severeLoginViolations).toEqual([]);

  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin-password");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Incident Summary" })).toBeVisible({ timeout: 30_000 });

  const workspaceResults = await new AxeBuilder({ page }).analyze();
  const severeWorkspaceViolations = workspaceResults.violations.filter((row) => ["serious", "critical"].includes(row.impact));
  expect(severeWorkspaceViolations).toEqual([]);
});

test("keyboard users can bypass navigation and the workspace reflows at mobile width", async ({ page }) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin-password");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Incident Summary" })).toBeVisible({ timeout: 30_000 });

  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "Skip to workspace content" });
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#workspace-content")).toBeFocused();

  await page.setViewportSize({ width: 320, height: 720 });
  const pageOverflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(pageOverflows).toBeFalsy();
  await expect(page.getByLabel("Navigate to")).toBeVisible();
});
