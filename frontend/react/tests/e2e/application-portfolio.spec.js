import { expect, test } from "@playwright/test";

test("application portfolio keeps selection beside each application", async ({ page }) => {
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path.includes("applications")
          ? { rows: [{ id: "app-1", name: "Checkout", environment: "prod", owner_team: "platform-ops", technology: "fastapi", status: "dashboard_created" }] }
          : path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent")
            ? { data: { rows: [{ service: "payments", application: "Payments" }] } }
            : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/applications");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Application Portfolio" })).toBeVisible();
  const checkoutRow = page.getByRole("row").filter({ hasText: "Checkout" });
  await expect(checkoutRow.getByLabel("Select Checkout")).toBeVisible();
  await checkoutRow.getByLabel("Select Checkout").check();
  await expect(page.getByRole("button", { name: "Remove selected (1)" })).toBeEnabled();
});
