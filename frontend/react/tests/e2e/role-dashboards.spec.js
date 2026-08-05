import { expect, test } from "@playwright/test";

const roles = [
  { role: "L1 Operator", eyebrow: "Operator dashboard", heading: "What requires attention now?", metric: "Active Alerts" },
  { role: "L2 Engineer", eyebrow: "Approver dashboard", heading: "Decisions requiring review", metric: "Pending Approvals" },
  { role: "Executive", eyebrow: "Executive dashboard", heading: "Business reliability attention", metric: "Automation Rate" },
  { role: "Administrator", eyebrow: "Administrator dashboard", heading: "Platform attention", metric: "Connector Health" },
];

for (const scenario of roles) {
  test(`${scenario.role} receives its attention dashboard with metric definitions`, async ({ page }) => {
    await page.route("**/api-gateway/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
      const body = path === "/auth/login"
        ? { access_token: `${scenario.role}-token`, refresh_token: "refresh-token", user: { id: 1, username: "test-user", role_name: scenario.role } }
        : path === "/healthz"
          ? { status: "ok", service: "api-gateway" }
          : path === "/applications"
            ? { data: { rows: [{ id: "app-1", name: "KaiOps", status: "dashboard_created" }] } }
            : path.startsWith("/alerts/all")
              ? { data: { rows: [{ id: "alert-1", name: "CPU high", service: "checkout", severity: "critical", status: "active", source: "prometheus" }] } }
              : { data: { rows: [] }, rows: [], summary: {}, items: [] };
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    });

    await page.goto("/");
    await page.getByLabel("Username").fill("test-user");
    await page.getByLabel("Password").fill("Test@123456");
    await page.getByRole("button", { name: "Sign In" }).click();
    const dashboard = page.locator(".role-dashboard");
    await expect(dashboard.getByText(scenario.eyebrow, { exact: true })).toBeVisible();
    await expect(dashboard.getByRole("heading", { name: scenario.heading, exact: true })).toBeVisible();
    await expect(dashboard.getByText(scenario.metric, { exact: true })).toBeVisible();
    await expect(dashboard).toContainText("Asia/Kolkata (IST)");
    await dashboard.getByText("Metric definitions and data quality", { exact: true }).click();
    await expect(dashboard).toContainText("They are not interchangeable totals");
  });
}
