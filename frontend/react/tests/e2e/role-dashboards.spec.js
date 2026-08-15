import { expect, test } from "@playwright/test";

const roles = ["L1 Operator", "L2 Engineer", "Executive", "Administrator"];

for (const role of roles) {
  test(`${role} receives the reliability overview with its role identity`, async ({ page }) => {
    await page.route("**/api-gateway/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
      const body = path === "/auth/login"
        ? { access_token: `${role}-token`, refresh_token: "refresh-token", user: { id: 1, username: "test-user", role_name: role } }
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
    await expect(page.getByRole("heading", { level: 1, name: "Incident Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Reliability Overview" })).toBeVisible();
    await expect(page.locator(".hero-user")).toContainText(role);
    await expect(page.getByText("Overall SLO Score", { exact: true })).toBeVisible();
  });
}
