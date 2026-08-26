import { expect, test } from "@playwright/test";

test("resource explorer loads inventory through the authenticated gateway", async ({ page }) => {
  let resourceRequest = null;
  await page.route("**/api-gateway/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api-gateway/, "");
    if (path === "/cloud-ops/resources") {
      resourceRequest = {
        authorization: request.headers().authorization,
        url: request.url(),
      };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: {
            rows: [{
              id: "resource-1",
              tenant_id: "default",
              project_id: "demo-project",
              connection_id: "connection-1",
              provider: "simulator",
              provider_resource_id: "simulator://checkout-api",
              resource_type: "service",
              display_name: "checkout-api",
              environment: "prod",
              service_id: "checkout-api",
              status: "healthy",
            }],
            count: 1,
          },
        }),
      });
    }
    if (path.startsWith("/cloud-ops/services/") && path.endsWith("/topology")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { nodes: [], edges: [] } }) });
    }
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path === "/applications"
          ? { data: { rows: [] } }
          : { data: [], rows: [], summary: {}, items: [] };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/cloud-ops/resources");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Resource Explorer" })).toBeVisible();
  await expect(page.getByText("checkout-api", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(resourceRequest).toMatchObject({ authorization: "Bearer admin-token" });
  expect(resourceRequest.url).toContain("/api-gateway/cloud-ops/resources?project_id=demo-project");
});
