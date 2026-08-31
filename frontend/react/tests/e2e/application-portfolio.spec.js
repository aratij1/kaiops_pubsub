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

test("observed applications can start authenticated registration", async ({ page }) => {
  let registrationRequest = null;
  await page.route("**/api-gateway/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api-gateway/, "");
    if (path === "/applications" && request.method() === "POST") {
      registrationRequest = {
        authorization: request.headers().authorization,
        body: request.postDataJSON(),
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ application: { id: "app-payments", ...registrationRequest.body }, status: "queued" }),
      });
    }
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path === "/applications"
          ? { data: { rows: [] } }
          : path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent")
            ? { data: { rows: [{ service: "payments", application: "Payments" }] } }
            : { data: [], rows: [], summary: {}, items: [] };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/applications");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("button", { name: "Register application" }).click();
  await expect(page.getByRole("heading", { name: "Register application" })).toBeVisible();
  await page.getByLabel("Application name", { exact: true }).fill("Payments");
  await page.getByRole("button", { name: "Register and start onboarding" }).click();
  await expect(page.getByText("Payments was registered and queued for onboarding.")).toBeVisible();
  expect(registrationRequest).toMatchObject({
    authorization: "Bearer admin-token",
    body: {
      tenant_id: "default",
      name: "Payments",
      environment: "prod",
      monitoring_platform: "prometheus",
    },
  });
});
