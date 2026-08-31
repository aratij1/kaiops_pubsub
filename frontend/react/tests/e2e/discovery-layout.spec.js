import { expect, test } from "@playwright/test";

test("live alert discovery is a first-class responsive operational view", async ({ page }) => {
  const rows = [{ id: "discovery-alert-1", alert_id: "discovery-alert-1", name: "Pod crash loop", service: "checkout", application: "KaiOps", severity: "critical", status: "active", source: "prometheus", labels: { project_name: "KaiOps" } }];
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path === "/healthz"
          ? { status: "ok", service: "api-gateway" }
          : path.startsWith("/alerts/all")
            ? { data: { rows } }
            : { data: { rows: [] }, rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/alerts");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Operations Feed" })).toBeVisible();
  await expect(page.getByRole("radiogroup", { name: "Alerts and streams view" })).toBeVisible();
  await expect(page.getByText("Pod crash loop", { exact: true }).first()).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
