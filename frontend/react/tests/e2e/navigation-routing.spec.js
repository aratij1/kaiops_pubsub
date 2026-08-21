import { expect, test } from "@playwright/test";

test("legacy bookmarks and canonical navigation survive route changes", async ({ page }) => {
  test.setTimeout(90_000);
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
      ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
      : path === "/healthz"
        ? { status: "ok", service: "api-gateway" }
        : path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications"
          ? { data: { rows: [] } }
          : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/approval-queue-legacy");
  await expect(page).toHaveURL(/\/approvals$/, { timeout: 30_000 });
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();

  await expect(page).toHaveTitle("My Approvals | KaiMS");
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Review work");
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("My Approvals");
  await page.getByRole("button", { name: "Operations Overview", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Operations Overview" })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 500));
  const savedDashboardScroll = await page.evaluate(() => window.scrollY);
  expect(savedDashboardScroll).toBeGreaterThan(0);

  await page.getByRole("button", { name: "Alert Stream", exact: true }).click();
  await expect(page).toHaveURL(/\/alerts$/);
  await expect(page).toHaveTitle("Alert Stream | KaiMS");
  await page.getByRole("button", { name: "Operations Overview", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Operations Overview" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileNavigation = page.getByLabel("Navigate to");
  await expect(mobileNavigation).toBeVisible();
  await mobileNavigation.selectOption("/applications");
  await expect(page).toHaveURL(/\/applications$/);
  await expect(page).toHaveTitle("Projects & Integrations | KaiMS");
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Administration");
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Projects & Integrations");
});

test("a restricted deep link redirects without exposing administrative navigation", async ({ page }) => {
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
      ? { access_token: "operator-token", refresh_token: "refresh-token", user: { id: 2, username: "operator", role_name: "L1 Operator" } }
      : path === "/healthz"
        ? { status: "ok", service: "api-gateway" }
        : { data: { rows: [] }, rows: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/admin");
  await page.getByLabel("Username").fill("operator");
  await page.getByLabel("Password").fill("Operator@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).not.toContainText("Administration");
});
